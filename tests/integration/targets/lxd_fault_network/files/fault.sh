#!/bin/sh
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Network faults between the controller and one LXD server, with iptables on the controller.
#
#   fault.sh start <ip> <port> <mode> <delay> <seconds>   in the background: wait <delay> s, add the
#                                                          rules, keep them <seconds> s (0: until clear)
#   fault.sh clear                                         remove every rule of this script
#
# Modes:
#   drop    packets in both directions are lost; the connection stalls, then goes on
#   reset   new and open connections fail at once (TCP reset); answers of the server are lost
#   slow    the server can send about 2000 packets per second (about 3 MB/s)
set -eu
TAG=lxd-fault

clear_rules() {
  for chain in OUTPUT INPUT; do
    iptables -S "$chain" | grep -- "--comment $TAG" | sed 's/^-A /-D /' | while read -r rule; do
      # shellcheck disable=SC2086
      iptables $rule
    done
  done
}

add_rules() {
  ip=$1 port=$2 mode=$3
  case "$mode" in
    drop)
      iptables -I OUTPUT -d "$ip" -p tcp --dport "$port" -m comment --comment "$TAG" -j DROP
      iptables -I INPUT -s "$ip" -p tcp --sport "$port" -m comment --comment "$TAG" -j DROP
      ;;
    reset)
      iptables -I OUTPUT -d "$ip" -p tcp --dport "$port" -m comment --comment "$TAG" -j REJECT --reject-with tcp-reset
      iptables -I INPUT -s "$ip" -p tcp --sport "$port" -m comment --comment "$TAG" -j DROP
      ;;
    slow)
      iptables -I INPUT -s "$ip" -p tcp --sport "$port" -m comment --comment "$TAG" \
        -m hashlimit --hashlimit-above 2000/sec --hashlimit-burst 2000 --hashlimit-mode srcip --hashlimit-name "$TAG" -j DROP
      ;;
    *)
      echo "unknown mode $mode" >&2
      exit 2
      ;;
  esac
}

case "${1:-}" in
  start)
    ip=$2 port=$3 mode=$4 delay=$5 seconds=$6
    (
      sleep "$delay"
      add_rules "$ip" "$port" "$mode"
      if [ "$seconds" -gt 0 ]; then
        sleep "$seconds"
        # Remove only the rules of this mode, so that a slow link stays slow.
        for chain in OUTPUT INPUT; do
          iptables -S "$chain" | grep -- "--comment $TAG" | grep -v hashlimit | sed 's/^-A /-D /' | while read -r rule; do
            # shellcheck disable=SC2086
            iptables $rule
          done
        done
      fi
    ) >/dev/null 2>&1 &
    ;;
  clear)
    clear_rules
    ;;
  *)
    echo "usage: fault.sh start <ip> <port> <mode> <delay> <seconds> | clear" >&2
    exit 2
    ;;
esac
