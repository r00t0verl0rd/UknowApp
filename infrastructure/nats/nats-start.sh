#!/bin/sh
set -eu

if [ -n "${MAX_PASSWORD:-}" ]; then
  exec nats-server -c /etc/nats/nats-max.conf
fi

exec nats-server -c /etc/nats/nats.conf
