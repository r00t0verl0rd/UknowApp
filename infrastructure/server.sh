#!/usr/bin/env bash
# Invoked by deploy.sh over SSH. Never use bash -x: this script handles secrets.
set -Eeuo pipefail
umask 077
trap 'echo "ERROR: server step ${ACTION:-?}, line $LINENO (exit $?)" >&2' ERR
fail(){ echo "ERROR: $*" >&2; exit 1; }
log(){ echo "[$ROLE] $*" >&2; }
[[ $EUID == 0 ]] || fail 'root required'
ACTION=${1:?action}; ROLE=${2:?role}; MAIN_IP=${3:?main IP}; TG_IP=${4:?telegram IP}; shift 4
[[ $ROLE == main || $ROLE == telegram ]] || fail 'invalid role'
[[ $MAIN_IP =~ ^[0-9.]+$ && $TG_IP =~ ^[0-9.]+$ ]] || fail 'IPv4 required'
WG=wg-uknow; MOUNT=/srv/uknow-telegram-remote; CACHE=/srv/uknow-telegram
REPO=https://github.com/r00t0verl0rd/UknowApp.git
REF=588dc99079f0fc7449f80f621856ac42904c8639
IMAGE=aiogram/telegram-bot-api@sha256:0ed088d2ffcc1dbca294813d6949799747c64294aaff931437b8d18e671f4c20
STATE=/var/lib/uknow-deploy
if [[ $ROLE == main ]]; then USERNAME=uknow; OWN_IP=10.77.0.1; PEER_IP=10.77.0.2; else USERNAME=uknowbot; OWN_IP=10.77.0.2; PEER_IP=10.77.0.1; fi
APP=/home/$USERNAME/UknowApp
install -d -m 700 "$STATE"
# Only create a new config or accept an exact existing config. Never replace an unknown file.
managed(){ local path=$1 mode=${2:-644} tmp; tmp=$(mktemp); cat > "$tmp"; if [[ -e $path ]]; then if ! cmp -s "$tmp" "$path"; then rm -f "$tmp"; fail "Existing configuration differs: $path; review manually"; fi; else install -D -m "$mode" "$tmp" "$path"; fi; rm -f "$tmp"; }
packages(){ local p; local -a missing=(); for p in "$@"; do if ! dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -qx 'install ok installed'; then missing+=("$p"); fi; done; if ((${#missing[@]})); then apt-get update >&2; DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y "${missing[@]}" >&2; fi; }
user_docker(){ if ! id "$USERNAME" >/dev/null 2>&1; then useradd -m -s /bin/bash "$USERNAME"; fi; [[ $(getent passwd "$USERNAME" | cut -d: -f6) == /home/$USERNAME ]] || fail 'unexpected home directory'; if ! docker compose version >/dev/null 2>&1; then packages docker.io docker-compose; fi; systemctl enable --now docker.service >&2; usermod -aG docker "$USERNAME"; }
repo(){ if [[ ! -d $APP/.git ]]; then [[ ! -e $APP ]] || fail "$APP already exists without .git"; runuser -u "$USERNAME" -- git clone "$REPO" "$APP" >&2; runuser -u "$USERNAME" -- git -C "$APP" checkout --detach "$REF" >&2; fi; [[ $(runuser -u "$USERNAME" -- git -C "$APP" rev-parse HEAD) == "$REF" ]] || fail "Expected commit $REF; existing repo not changed"; [[ -z $(runuser -u "$USERNAME" -- git -C "$APP" status --porcelain --untracked-files=no) ]] || fail 'tracked repository files modified'; cd "$APP"; }
compose(){ docker compose "$@"; }
tgcompose(){ docker compose -f compose.telegram.yml "$@"; }
# Edit only named entries. Input values arrive on stdin, never as CLI arguments.
edit_env(){ python3 -c 'import os,re,sys,tempfile
p=sys.argv[1]; st=os.stat(p); updates={}
for line in sys.stdin:
 k,v=line.rstrip("\n").split("=",1)
 if not re.fullmatch(r"[A-Z_][A-Z0-9_]*",k) or "\r" in v or "\x00" in v: raise SystemExit("Invalid env input")
 if re.fullmatch(r"[a-zA-Z0-9_./:@,\-]*",v): updates[k]=v
 elif chr(39) not in v and chr(92) not in v: updates[k]=chr(39)+v+chr(39)
 else: raise SystemExit("Unsupported quote/backslash in value")
with open(p) as f: lines=f.readlines()
out=[]; seen=set()
for line in lines:
 m=re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=",line)
 if m and m[1] in updates:
  k=m[1]
  if k not in seen: out.append(k+"="+updates[k]+"\n"); seen.add(k)
 else: out.append(line if line.endswith("\n") else line+"\n")
for k,v in updates.items():
 if k not in seen: out.append(k+"="+v+"\n")
fd,t=tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(p)))
try:
 os.fchown(fd,st.st_uid,st.st_gid); os.fchmod(fd,0o600)
 with os.fdopen(fd,"w") as f: f.writelines(out); f.flush(); os.fsync(f.fileno())
 os.replace(t,p)
finally:
 if os.path.exists(t): os.unlink(t)' "$APP/.env"; }
config_value(){ compose config --format json | python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["backend"]["environment"]; print(e.get(sys.argv[1],""))' "$1"; }
mode(){ config_value TELEGRAM_API_MODE; }
secret_prompt(){ local name=$1 label=$2; read -r -s -p "$label: " "$name" </dev/tty; printf '\n' >/dev/tty; }
check_mount(){ [[ $(findmnt -n -M "$MOUNT" -o SOURCE,FSTYPE) == '10.77.0.2:/ nfs4' ]] || fail 'NFS source/type differs or is not mounted'; findmnt -n -M "$MOUNT" -o OPTIONS | grep -Eq '(^|,)ro(,|$)' || fail 'NFS not read-only'; if [[ $(timeout 25 cat "$MOUNT/.uknow-deploy-probe" 2>/dev/null || true) != 'Uknow deploy probe' ]]; then [[ $(timeout 25 cat "$MOUNT/.nfs-test" 2>/dev/null || true) == 'Uknow NFS test OK' ]] || fail 'NFS read probe failed'; fi; }
check_http(){ local code; code=$(curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{http_code}' http://10.77.0.2:8081/); [[ $code == 404 ]] || fail "Telegram HTTP root returned $code, expected 404"; }
check_backend_files(){ local id image uidgid; id=$(compose ps -a -q backend); if [[ -n $id ]]; then image=$(docker inspect "$id" --format '{{.Image}}'); else image=$(compose config --format json | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["services"]["backend"].get("image") or j["name"]+"-backend")'); docker image inspect "$image" >/dev/null; fi; uidgid=$(docker run --rm --network none --entrypoint python "$image" -c 'import os;print(f"{os.getuid()}:{os.getgid()}")'); [[ $uidgid != 0:* ]] || fail 'backend image runs as root'; docker run --rm --network none --user "$uidgid" --mount "type=bind,source=$MOUNT,target=/var/lib/telegram-bot-api,readonly" --entrypoint python "$image" -c 'assert open("/var/lib/telegram-bot-api/.uknow-deploy-probe").read().strip()=="Uknow deploy probe"; print("NFS backend UID check OK")' >&2; }
case "$ACTION" in
init)
  . /etc/os-release; [[ $ID == debian && $VERSION_ID == 13 ]] || fail 'Only Debian 13 supported'; [[ $(uname -m) == x86_64 ]] || fail 'Only x86_64 tested configuration';
  packages git curl ca-certificates python3 wireguard
  install -d -m 700 /etc/wireguard
  if [[ ! -f /etc/wireguard/uknow.key ]]; then [[ ! -e /etc/wireguard/$WG.conf && ! -e /etc/wireguard/uknow.pub ]] || fail 'existing WireGuard configuration/key without private key'; wg genkey > /etc/wireguard/uknow.key; fi
  chmod 600 /etc/wireguard/uknow.key
  pub=$(wg pubkey < /etc/wireguard/uknow.key)
  if [[ -e /etc/wireguard/uknow.pub ]]; then [[ $(cat /etc/wireguard/uknow.pub) == "$pub" ]] || fail 'WireGuard public/private mismatch'; else printf '%s\n' "$pub" > /etc/wireguard/uknow.pub; fi
  log 'WireGuard key ready'
  ;;
public) cat /etc/wireguard/uknow.pub;;
wire)
  peer=${1:?peer public key}; [[ $peer =~ ^[A-Za-z0-9+/]{43}=$ ]] || fail 'bad public key'
  if [[ ! -e /etc/wireguard/$WG.conf ]]; then
    # A fresh tunnel must not overlap any existing route.
    python3 -c 'import ipaddress,json,subprocess
net=ipaddress.ip_network("10.77.0.0/24")
for r in json.loads(subprocess.check_output(["ip","-j","-4","route","show","table","all"])):
 d=r.get("dst","default")
 if d!="default" and ipaddress.ip_network(d,strict=False).overlaps(net): raise SystemExit("WireGuard subnet overlaps existing route: "+d)'
  fi
  { printf '[Interface]\nAddress = %s/24\n' "$OWN_IP"; [[ $ROLE != telegram ]] || printf 'ListenPort = 51820\n'; printf 'PrivateKey = %s\n\n[Peer]\nPublicKey = %s\n' "$(cat /etc/wireguard/uknow.key)" "$peer"; [[ $ROLE != main ]] || printf 'Endpoint = %s:51820\n' "$TG_IP"; printf 'AllowedIPs = %s/32\n' "$PEER_IP"; [[ $ROLE != main ]] || printf 'PersistentKeepalive = 25\n'; } | managed /etc/wireguard/$WG.conf 600
  systemctl enable --now wg-quick@$WG.service >&2
  [[ $(wg show "$WG" peers) == "$peer" ]] || fail 'running WireGuard peer differs'
  ip -4 addr show dev "$WG" | grep -Fq "$OWN_IP/24" || fail 'WireGuard address differs'
  ;;
firewall)
  [[ $ROLE == telegram ]] || fail 'wrong role'; packages nftables
  ext=$(ip -4 route get "$MAIN_IP" | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1);exit}}'); [[ $ext =~ ^[A-Za-z0-9_.:-]+$ && $ext != "$WG" ]] || fail 'cannot determine WAN interface'
  # Do not adopt an arbitrary existing nftables/iptables firewall.
  if [[ ! -e /etc/nftables.d/uknow.nft ]]; then
    if nft list tables | grep -Ev '^table ip6? (filter|nat)$' | grep -q .; then fail 'other nftables tables exist; review firewall manually'; fi
    if command -v iptables >/dev/null && ! iptables -S INPUT | grep -qx -- '-P INPUT ACCEPT'; then fail 'custom IPv4 INPUT policy'; fi
    if command -v iptables >/dev/null && iptables -S INPUT | grep -q '^-A '; then fail 'custom IPv4 INPUT rules'; fi
    if command -v ip6tables >/dev/null && ip6tables -S INPUT | grep -q '^-A '; then fail 'custom IPv6 INPUT rules'; fi
  fi
  managed /etc/nftables.d/uknow.nft <<EOF
add table inet uknow_guard
flush table inet uknow_guard

table inet uknow_guard {
    chain input {
        type filter hook input priority -10; policy drop;

        iifname "lo" accept
        ct state established,related accept

        ip protocol icmp accept
        meta l4proto ipv6-icmp accept

        tcp dport 22 accept

        ip saddr $MAIN_IP udp dport 51820 accept

        iifname "wg-uknow" ip saddr 10.77.0.1 tcp dport { 8081, 2049 } accept
    }

    chain forward {
        type filter hook forward priority -10; policy accept;

        iifname "$ext" ct state new drop
    }
}
EOF
  nft -c -f /etc/nftables.d/uknow.nft
  if ! nft list table inet uknow_guard >/dev/null 2>&1; then
    systemctl stop uknow-deploy-fw-rollback.timer 2>/dev/null || true
    systemd-run --unit=uknow-deploy-fw-rollback --on-active=5min /usr/sbin/nft delete table inet uknow_guard >&2
    nft -f /etc/nftables.d/uknow.nft
  fi
  ;;
firewall-commit)
  [[ $ROLE == telegram ]] || fail 'wrong role'
  nft list table inet uknow_guard >/dev/null || fail 'firewall rollback occurred; run again'
  managed /etc/systemd/system/uknow-firewall.service <<'EOF'
[Unit]
Description=Uknow Firewall
Wants=network-pre.target
Before=network-pre.target docker.service nfs-server.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.d/uknow.nft
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload; systemctl enable --now uknow-firewall.service >&2
  systemctl stop uknow-deploy-fw-rollback.timer 2>/dev/null || true
  nft -f /etc/nftables.d/uknow.nft
  ;;
telegram)
  [[ $ROLE == telegram ]] || fail 'wrong role'; systemctl is-active --quiet uknow-firewall.service || fail 'firewall not active'
  user_docker; repo
  managed /etc/systemd/system/docker.service.d/uknow.conf <<'EOF'
[Unit]
Requires=wg-quick@wg-uknow.service uknow-firewall.service
After=wg-quick@wg-uknow.service uknow-firewall.service
EOF
  systemctl daemon-reload
  if [[ ! -e .env ]]; then
    secret_prompt apiid 'Telegram API ID (my.telegram.org)'; secret_prompt apihash 'Telegram API Hash'
    [[ $apiid =~ ^[0-9]+$ && $apihash =~ ^[[:xdigit:]]{32}$ ]] || fail 'Invalid API ID/Hash format'
    tmp=$(mktemp); printf 'TELEGRAM_API_ID=%s\nTELEGRAM_API_HASH=%s\nTELEGRAM_LISTEN_IP=10.77.0.2\nTELEGRAM_CACHE_HOST_DIR=%s\nTELEGRAM_API_IMAGE=%s\n' "$apiid" "$apihash" "$CACHE" "$IMAGE" > "$tmp"; install -m 600 -o "$USERNAME" -g "$(id -gn "$USERNAME")" "$tmp" .env; rm -f "$tmp"; unset apiid apihash
  fi
  [[ $(stat -c %a .env) == 600 ]] || fail 'existing Telegram .env must have mode 600'
  tgcompose config --quiet
  tgcompose config --format json | python3 -c 'import json,sys,re
s=json.load(sys.stdin)["services"]["telegram-bot-api"]; e=s["environment"]; p=s["ports"]; v=s["volumes"]
assert re.fullmatch(r"[0-9]+",str(e.get("TELEGRAM_API_ID",""))) and re.fullmatch(r"[a-fA-F0-9]{32}",e.get("TELEGRAM_API_HASH","")),"Invalid API credentials"
assert len(p)==1 and p[0].get("host_ip")=="10.77.0.2" and str(p[0]["published"])=="8081" and p[0]["target"]==8081,"Unexpected API port"
assert any(x.get("source")=="/srv/uknow-telegram" and x.get("target")=="/var/lib/telegram-bot-api" for x in v),"Unexpected cache mount"
assert str(e.get("TELEGRAM_LOCAL"))=="1","Not local mode"'
  img=$(tgcompose config --images); [[ $img == aiogram/telegram-bot-api:* || $img == aiogram/telegram-bot-api@sha256:* ]] || fail 'Unexpected image'; if ! docker image inspect "$img" >/dev/null 2>&1; then docker pull "$img" >&2; fi
  [[ $(docker run --rm --network none --entrypoint /bin/sh "$img" -c 'printf "%s:%s" "$(id -u telegram-bot-api)" "$(id -g telegram-bot-api)"') == 101:101 ]] || fail 'Telegram image UID/GID changed'
  if [[ ! -e $CACHE ]]; then install -d -m 0700 -o 101 -g 101 "$CACHE"; fi
  [[ $(stat -c '%u:%g:%a' "$CACHE") == 101:101:700 ]] || fail 'unexpected Telegram cache ownership or mode'
  runuser -u "$USERNAME" -- docker compose -f compose.telegram.yml up -d --no-recreate >&2
  cid=$(tgcompose ps -q telegram-bot-api); [[ -n $cid ]] || fail 'Telegram container not running'
  docker inspect "$cid" | python3 -c 'import json,sys; c=json.load(sys.stdin)[0]; p=c["HostConfig"]["PortBindings"]; assert p.get("8081/tcp")==[{"HostIp":"10.77.0.2","HostPort":"8081"}],"Running API port differs"; assert any(x["Source"]=="/srv/uknow-telegram" and x["Destination"]=="/var/lib/telegram-bot-api" and x["RW"] for x in c["Mounts"]),"Running cache differs"' 
  for i in {1..20}; do if docker top "$cid" -eo uid,gid,comm | awk '$1==101 && $2==101 && $3 ~ /^telegram-bot/ {f=1} END{exit !f}'; then break; fi; sleep 1; done
  docker top "$cid" -eo uid,gid,comm | awk '$1==101 && $2==101 && $3 ~ /^telegram-bot/ {f=1} END{exit !f}' || fail 'Telegram process not running as 101:101'
  for i in {1..20}; do if curl -s --max-time 2 -o /dev/null -w '%{http_code}' http://10.77.0.2:8081/ | grep -qx 404; then break; fi; sleep 1; done; check_http
  # NFS packages are installed only after the external firewall is active.
  packages nfs-kernel-server
  managed /etc/nfs.conf.d/uknow.conf <<'EOF'
[nfsd]
host=10.77.0.2
vers3=n
vers4=y
tcp=y
udp=n
EOF
  managed /etc/exports.d/uknow.exports <<'EOF'
/srv/uknow-telegram 10.77.0.1(ro,sync,no_subtree_check,all_squash,anonuid=101,anongid=101,fsid=0)
EOF
  managed /etc/systemd/system/nfs-server.service.d/uknow.conf <<'EOF'
[Unit]
Requires=wg-quick@wg-uknow.service uknow-firewall.service
After=wg-quick@wg-uknow.service uknow-firewall.service
EOF
  systemctl daemon-reload
  # Package installation may have started NFS with default listeners. Restart only if necessary.
  if systemctl is-active --quiet nfs-server.service && ss -H -ltn 'sport = :2049' | awk '$4!="10.77.0.2:2049" {bad=1} END{exit !bad}'; then systemctl restart nfs-server.service; fi
  systemctl enable --now nfs-server.service >&2; exportfs -ra
  ss -H -ltn 'sport = :2049' | awk '$4=="10.77.0.2:2049" {ok=1} $4!="10.77.0.2:2049" {bad=1} END{exit !(ok&&!bad)}' || fail 'NFS not exclusively bound to WireGuard'
  grep -q -- '-3' /proc/fs/nfsd/versions || fail 'NFSv3 enabled'
  if [[ ! -e $CACHE/.uknow-deploy-probe ]]; then printf 'Uknow deploy probe\n' > "$CACHE/.uknow-deploy-probe"; chown 101:101 "$CACHE/.uknow-deploy-probe"; chmod 600 "$CACHE/.uknow-deploy-probe"; fi
  log 'Telegram API and NFS ready'
  ;;
main-prepare)
  [[ $ROLE == main ]] || fail 'wrong role'; packages nfs-common; user_docker; repo
  if [[ ! -e .env ]]; then
    # This revision has uknowschool.ru hard-coded in frontend/Caddyfile.
    domain=uknowschool.ru
    log "Fresh install uses $domain (and www.$domain); configure DNS separately"
    secret_prompt admin 'Admin password (at least 16 chars; no single quote or backslash)'; [[ ${#admin} -ge 16 && $admin != *\'* && $admin != *\\* ]] || fail 'unsupported admin password'
    secret_prompt bot 'BotFather token'; [[ $bot =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || fail 'Invalid bot token format'
    install -m 600 -o "$USERNAME" -g "$(id -gn "$USERNAME")" .env.example .env
    printf 'DOMAIN=%s\nADMIN_PASSWORD=%s\nTELEGRAM_BOT_TOKEN=%s\n' "$domain" "$admin" "$bot" | edit_env
    unset admin bot
  fi
  [[ $(stat -c %a .env) == 600 ]] || fail 'existing main .env must have mode 600'
  compose config --quiet
  # Preserve other profiles (e.g. postgres), but refuse same-host Telegram.
  project=$(compose config --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')
  if [[ -n $(docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=telegram-bot-api") ]]; then fail 'same-host Telegram container exists; manual migration needed'; fi
  compose config --format json | python3 -c 'import json,sys,re
s=json.load(sys.stdin)["services"]; e=s["backend"]["environment"]
assert "telegram" not in [p.strip() for p in e.get("COMPOSE_PROFILES", "").split(",")],"Same-host Telegram profile enabled"
assert e.get("ADMIN_PASSWORD") != "replace-with-a-long-random-password","Replace example admin password"
assert re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+",e.get("TELEGRAM_BOT_TOKEN","")),"Bot token missing/invalid"
assert str(e.get("TELEGRAM_BOT_ENABLED","")).lower() in ("true","1","yes","on"),"Telegram disabled; enable explicitly first"
assert e.get("TELEGRAM_API_MODE") in ("cloud","local"),"Unknown API mode"
if e["TELEGRAM_API_MODE"]=="local":
 assert e.get("TELEGRAM_API_URL")=="http://10.77.0.2:8081","Existing local Telegram endpoint differs"
 assert any(x.get("source")=="/srv/uknow-telegram-remote" and x.get("target")=="/var/lib/telegram-bot-api" and x.get("read_only") for x in s["backend"]["volumes"]),"Existing local cache path differs"'
  ping -c 2 -W 2 10.77.0.2 >&2; check_http
  mkdir -p "$MOUNT"
  fstab_line='10.77.0.2:/ /srv/uknow-telegram-remote nfs ro,vers=4.2,soft,timeo=50,retrans=2,_netdev,nofail,x-systemd.requires=wg-quick@wg-uknow.service,x-systemd.mount-timeout=20s 0 0'
  if awk '$1!~/^#/ && $2=="/srv/uknow-telegram-remote" {found=1} END{exit !found}' /etc/fstab; then grep -Fxq "$fstab_line" /etc/fstab || fail 'existing fstab mount differs'; else cp -a /etc/fstab "$STATE/fstab.before"; printf '\n%s\n' "$fstab_line" >> /etc/fstab; fi
  unit=$(systemd-escape --path --suffix=mount "$MOUNT")
  managed /etc/systemd/system/docker.service.d/uknow-nfs.conf <<EOF
[Unit]
Wants=$unit
After=$unit
EOF
  systemctl daemon-reload; systemctl start "$unit"; check_mount
  if [[ -z $(compose ps -a -q backend) ]]; then
    if ! docker buildx version >/dev/null 2>&1; then packages docker-buildx; fi
    compose build backend frontend >&2
  fi
  check_backend_files
  log 'Main prepared; running backend has not been stopped'
  ;;
state)
  cd "$APP"; m=$(mode); [[ $m == cloud || $m == local ]] || fail 'unexpected mode'; printf '%s\n' "$m"; [[ ! -e $STATE/logout.state ]] || cat "$STATE/logout.state";;
cloud-check)
  [[ $ROLE == telegram ]] || fail 'wrong role'; code=$(curl -4 -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{http_code}' https://api.telegram.org/); [[ $code != 000 ]] || fail 'cloud unreachable'; log "Cloud HTTP $code";;
stop-cloud)
  cd "$APP"; [[ $(mode) == cloud ]] || fail 'not in cloud mode'; check_mount; check_http
  [[ ! -e $STATE/logout.state ]] || fail 'previous migration pending; see README'
  backup=$(mktemp -d /root/uknow-backup-XXXXXXXX); cp -a .env "$backup/.env"; chmod 600 "$backup/.env"; printf '%s\n' "$REF" > "$backup/git-commit.txt"; log "Config backup: $backup (NOT a data backup)"
  compose stop backend >&2
  [[ -z $(compose ps -q backend) ]] || fail 'backend still running'
  printf 'pending\n' > "$STATE/logout.state"
  ;;
token)
  cd "$APP"; [[ $(mode) == cloud && $(cat "$STATE/logout.state") == pending && -z $(compose ps -q backend) ]] || fail 'cloud backend not stopped or migration state invalid'; config_value TELEGRAM_BOT_TOKEN;;
logout)
  [[ $ROLE == telegram ]] || fail 'wrong role'; python3 -c 'import sys,re,urllib.request,urllib.error,json
s=sys.stdin.read().strip()
if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+",s): raise SystemExit("Invalid token input")
try:
 req=urllib.request.Request("https://api.telegram.org/bot"+s+"/logOut",data=b"",method="POST")
 with urllib.request.urlopen(req,timeout=35) as r: j=json.load(r)
 if j.get("ok") is not True or j.get("result") is not True: raise SystemExit("logOut not confirmed")
 print("Cloud logOut OK")
except urllib.error.HTTPError as e: raise SystemExit("logOut HTTP error: "+str(e.code))
except Exception as e: raise SystemExit("logOut failed: "+type(e).__name__)';;
mark-logout)
  [[ $(cat "$STATE/logout.state") == pending ]] || fail 'invalid state'; printf 'confirmed\n' > "$STATE/logout.state";;
activate)
  cd "$APP"; check_mount; check_http; m=$(mode)
  if [[ $(config_value DATABASE_URL) == *'@postgres:'* ]]; then [[ -n $(compose ps -q postgres) ]] || fail 'PostgreSQL must already be running'; fi
  if [[ $m == cloud ]]; then [[ $(cat "$STATE/logout.state") == confirmed ]] || fail 'logOut not confirmed'; printf 'TELEGRAM_API_MODE=local\nTELEGRAM_API_URL=http://10.77.0.2:8081\nTELEGRAM_CACHE_HOST_DIR=%s\n' "$MOUNT" | edit_env; compose config --quiet; compose up -d --no-deps --force-recreate backend >&2; else
    [[ $m == local ]] || fail 'unexpected mode'; if [[ -z $(compose ps -q backend) ]]; then compose up -d --no-deps backend >&2; elif [[ $(compose exec -T backend printenv TELEGRAM_API_MODE) != local ]]; then compose up -d --no-deps --force-recreate backend >&2; fi
  fi
  if [[ -z $(compose ps -q frontend) ]]; then compose up -d frontend >&2; fi
  [[ ! -e $STATE/logout.state ]] || printf 'activated\n' > "$STATE/logout.state"
  ;;
verify)
  cd "$APP"; check_mount; check_http; [[ $(mode) == local ]] || fail 'not in local mode'
  cid=$(compose ps -q backend); [[ -n $cid ]] || fail 'backend not running'
  for i in {1..30}; do [[ $(docker inspect "$cid" --format '{{.State.Health.Status}}') != healthy ]] || break; sleep 3; done
  [[ $(docker inspect "$cid" --format '{{.State.Health.Status}}') == healthy ]] || fail 'backend not healthy'
  compose exec -T backend python -c 'import os,urllib.request,urllib.error
assert os.environ.get("TELEGRAM_API_MODE")=="local" and os.environ.get("TELEGRAM_API_URL")=="http://10.77.0.2:8081"
from pathlib import Path
p=Path("/var/lib/telegram-bot-api")
assert any((p/n).is_file() and (p/n).read_text().strip()==v for n,v in [(".uknow-deploy-probe","Uknow deploy probe"),(".nfs-test","Uknow NFS test OK")]),"NFS probe missing"
try: urllib.request.urlopen("http://10.77.0.2:8081/",timeout=5)
except urllib.error.HTTPError as e: assert e.code==404
print("Backend environment, NFS and API OK")'
  started=$(docker inspect "$cid" --format '{{.State.StartedAt}}');
  for marker in TELEGRAM_CONNECTED TELEGRAM_POLLING_STARTED; do
    found=0; for i in {1..20}; do if docker logs --since "$started" "$cid" 2>&1 | grep -F "$marker" >/dev/null; then found=1; break; fi; sleep 3; done; [[ $found == 1 ]] || fail "No $marker in current logs"; echo "$marker OK";
  done
  fid=$(compose ps -q frontend); [[ -n $fid ]] || fail 'frontend not running'
  for i in {1..30}; do [[ $(docker inspect "$fid" --format '{{.State.Health.Status}}') != healthy ]] || break; sleep 3; done
  [[ $(docker inspect "$fid" --format '{{.State.Health.Status}}') == healthy ]] || fail 'frontend not healthy'
  compose ps
  ;;
telegram-check)
  [[ $ROLE == telegram ]] || fail 'wrong role'; cd "$APP"
  for service in docker nfs-server wg-quick@wg-uknow uknow-firewall; do systemctl is-active --quiet "$service" || fail "$service inactive"; done
  nft list table inet uknow_guard >/dev/null; check_http
  ss -H -ltn 'sport = :2049' | awk '$4=="10.77.0.2:2049" {ok=1} $4!="10.77.0.2:2049" {bad=1} END{exit !(ok&&!bad)}' || fail 'NFS listener differs'
  cid=$(tgcompose ps -q telegram-bot-api); [[ -n $cid ]] || fail 'Telegram container not running'
  docker top "$cid" -eo uid,gid,comm | awk '$1==101 && $2==101 && $3 ~ /^telegram-bot/ {f=1} END{exit !f}' || fail 'Telegram UID/GID differs'
  tgcompose ps
  ;;
repair-mount)
  cd "$APP"; [[ $(mode) == local ]] || fail 'not in local mode'
  unit=$(systemd-escape --path --suffix=mount "$MOUNT")
  systemctl reset-failed "$unit" 2>/dev/null || true; systemctl start "$unit"; check_mount; check_http
  if compose exec -T backend python -c 'from pathlib import Path; p=Path("/var/lib/telegram-bot-api"); assert any((p/n).is_file() and (p/n).read_text().strip()==v for n,v in [(".uknow-deploy-probe","Uknow deploy probe"),(".nfs-test","Uknow NFS test OK")])' >/dev/null 2>&1; then log 'Backend sees NFS; no recreation needed'; else compose up -d --no-deps --force-recreate backend >&2; fi
  ;;
*) fail "Unknown action: $ACTION";;
esac
