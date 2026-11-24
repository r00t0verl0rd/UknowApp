#!/usr/bin/env bash
# Run from your workstation (macOS/Linux), not from either VPS.
set -Eeuo pipefail
usage(){ cat <<'EOF'
Usage: bash deploy.sh MAIN_PUBLIC_IPV4 TELEGRAM_PUBLIC_IPV4 [--prepare-only|--check|--repair-mount]
Defaults: full preparation, then explicit confirmation before cloud -> local cutover.
SSH: root@both servers, port 22; standard OpenSSH host key verification.
EOF
}
if [[ ${1:-} == --help || ${1:-} == -h ]]; then usage; exit 0; fi
[[ $# -ge 2 && $# -le 3 ]] || { usage >&2; exit 2; }
MAIN=$1; TG=$2; OPT=${3:---deploy}
case "$OPT" in --deploy|--prepare-only|--check|--repair-mount) ;; *) usage >&2; exit 2;; esac
valid_ip(){ local IFS=. a b c d oct; [[ $1 =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || return 1; read -r a b c d <<< "$1"; for oct in "$a" "$b" "$c" "$d"; do [[ $oct == 0 || $oct != 0* ]] && ((10#$oct <= 255)) || return 1; done; }
valid_ip "$MAIN" && valid_ip "$TG" && [[ $MAIN != "$TG" ]] || { echo 'Two distinct IPv4 addresses required.' >&2; exit 2; }
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); [[ -f $DIR/server.sh ]] || { echo 'server.sh missing' >&2; exit 2; }
[[ -t 0 ]] || { echo 'Run from an interactive terminal.' >&2; exit 2; }
command -v ssh >/dev/null || { echo 'OpenSSH required' >&2; exit 2; }
TMP=$(mktemp -d /tmp/uknow-deploy.XXXXXX); chmod 700 "$TMP"
MFILE= TFILE=; STAGE=initialization
cleanup(){ local rc=$?; trap - EXIT; set +e
  [[ -z $MFILE ]] || ssh -o BatchMode=yes -o ConnectTimeout=5 -S "$TMP/m" -T "root@$MAIN" "rm -f -- '$MFILE'" >/dev/null 2>&1
  [[ -z $TFILE ]] || ssh -o BatchMode=yes -o ConnectTimeout=5 -S "$TMP/t" -T "root@$TG" "rm -f -- '$TFILE'" >/dev/null 2>&1
  ssh -S "$TMP/m" -O exit "root@$MAIN" >/dev/null 2>&1
  ssh -S "$TMP/t" -O exit "root@$TG" >/dev/null 2>&1
  rm -rf -- "$TMP"
  if ((rc)); then printf '\nStopped at step: %s. Exit: %s. No automatic rollback of data or bot session. Read README.md before retrying.\n' "$STAGE" "$rc" >&2; fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
step(){ STAGE=$1; printf '\n=== %s ===\n' "$STAGE"; }
ssh_m(){ ssh -S "$TMP/m" -T "root@$MAIN" "$@"; }
ssh_t(){ ssh -S "$TMP/t" -T "root@$TG" "$@"; }
# Arguments are fixed trusted action names, validated addresses and base64 public keys only.
m(){ ssh_m "bash '$MFILE' '$1' main '$MAIN' '$TG' ${2:+ '$2'}"; }
t(){ ssh_t "bash '$TFILE' '$1' telegram '$MAIN' '$TG' ${2:+ '$2'}"; }
mt(){ ssh -S "$TMP/m" -tt "root@$MAIN" "bash '$MFILE' '$1' main '$MAIN' '$TG'"; }
tt(){ ssh -S "$TMP/t" -tt "root@$TG" "bash '$TFILE' '$1' telegram '$MAIN' '$TG'"; }
step 'SSH connections (check host fingerprints; enter passwords if needed)'
ssh -M -S "$TMP/m" -o ControlPersist=no -o ConnectTimeout=10 -fN "root@$MAIN"
ssh -M -S "$TMP/t" -o ControlPersist=no -o ConnectTimeout=10 -fN "root@$TG"
# Remote scripts are temporary, root-owned, and contain no credentials.
MFILE=$(ssh_m 'umask 077; mktemp /root/uknow-deploy.XXXXXXXX.sh'); [[ $MFILE =~ ^/root/uknow-deploy\.[A-Za-z0-9]+\.sh$ ]] || exit 1
TFILE=$(ssh_t 'umask 077; mktemp /root/uknow-deploy.XXXXXXXX.sh'); [[ $TFILE =~ ^/root/uknow-deploy\.[A-Za-z0-9]+\.sh$ ]] || exit 1
ssh_m "cat > '$MFILE'; chmod 700 '$MFILE'" < "$DIR/server.sh"
ssh_t "cat > '$TFILE'; chmod 700 '$TFILE'" < "$DIR/server.sh"
if [[ $OPT == --check ]]; then step 'Read-only service checks'; t telegram-check; m verify; exit 0; fi
if [[ $OPT == --repair-mount ]]; then
  read -r -p 'Mount recovery may recreate backend. Type REPAIR: ' answer; [[ $answer == REPAIR ]] || exit 0
  step 'Recover NFS mount'; m repair-mount; m verify; exit 0
fi
printf '\nMain: root@%s\nTelegram: root@%s\n' "$MAIN" "$TG"
read -r -p 'Prepare these Debian 13 servers (Telegram VPS must be dedicated; SSH port 22)? Type PREPARE: ' answer
[[ $answer == PREPARE ]] || exit 0
step 'Install prerequisites and generate/reuse WireGuard keys'
m init; t init
MPUB=$(m public); TPUB=$(t public)
[[ $MPUB =~ ^[A-Za-z0-9+/]{43}=$ && $TPUB =~ ^[A-Za-z0-9+/]{43}=$ ]] || { echo 'Invalid public key' >&2; exit 1; }
step 'Configure WireGuard'
t wire "$MPUB"; m wire "$TPUB"
ssh_m 'ping -c 3 -W 2 10.77.0.2'; ssh_t 'ping -c 3 -W 2 10.77.0.1'
step 'Telegram firewall (temporary rollback guard)'
t firewall
# Independent new SSH session, not the existing multiplexed session.
ssh -o ControlMaster=no -S none -o ConnectTimeout=10 -T "root@$TG" 'true'
t firewall-commit
step 'Telegram Bot API and NFS (may prompt for API ID/Hash)'
tt telegram
step 'Main VPS preparation (may prompt for admin password and bot token)'
mt main-prepare
if [[ $OPT == --prepare-only ]]; then echo 'Prepared only; bot has not been switched. Run again without --prepare-only when ready.'; exit 0; fi
step 'Determine whether migration is needed'
state=$(m state)
case "$state" in
  local|$'local\nactivated'|$'local\nconfirmed')
    echo 'Local mode already configured; no cloud logOut will be issued.'
    step 'Ensure app running'; m activate;;
  cloud|$'cloud\nconfirmed')
    if [[ $state == cloud ]]; then t cloud-check; fi
    printf '\nCutover may briefly stop backend. Configuration will be backed up; user data will NOT.\nEnsure an external verified data backup exists (or confirm this is an empty installation).\nAfter successful cloud logOut, returning to cloud may be blocked for 10 minutes.\n'
    read -r -p 'To switch the existing bot, type MIGRATE: ' answer; [[ $answer == MIGRATE ]] || exit 0
    if [[ $state == cloud ]]; then
      step 'Stop cloud backend and save configuration'; m stop-cloud
      step 'Cloud logOut via Telegram VPS (token streamed over SSH, not printed)'
      m token | t logout
      m mark-logout
    fi
    step 'Activate local mode'; m activate;;
  $'cloud\npending') echo 'Previous logOut outcome unknown. Backend remains stopped. See README recovery; do not blindly retry or start cloud polling.' >&2; exit 1;;
  *) echo 'Unexpected migration state. Inspect the server; no cutover attempted.' >&2; exit 1;;
esac
step 'Verify backend health, environment, file access and polling logs'
m verify
printf '\nDeployment checks passed. Manually test real messages, photos, documents and voice notes in both directions.\n'
