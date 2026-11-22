#!/usr/bin/env bash
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tier 1: lint, docs, licenses, build, sanity, and unit tests. Runs on any machine with Python 3.11 or newer.
# Sanity and unit tests run with ansible-test --venv for each ansible-core version of CI_CORES.
#
# Environment:
#   NOX            nox command. Default: nox.
#   CI_PYTHON      Python version for ansible-test. Default: the version of python3.
#   SKIP_NOX       Set to 1 to skip the antsibull-nox sessions.
#   SKIP_TOOL_LINT Set to 1 to skip ruff and mypy of the CI code.
#   CI_CORES       ansible-core versions for sanity and unit tests, for example "2.20 2.21".
#                  Each one gets its own venv. Default: the minimum of meta/runtime.yml and the newest
#                  version that the Python of this run supports.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NOX="${NOX:-nox}"
CI_PYTHON="${CI_PYTHON:-$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')}"

# ansible-test needs the path ansible_collections/<namespace>/<name>.
case "$ROOT" in
  */ansible_collections/smcavoy/lxd) COLL="$ROOT" ;;
  *)
    TMP="$(mktemp -d)"
    mkdir -p "$TMP/ansible_collections/smcavoy"
    cp -R "$ROOT" "$TMP/ansible_collections/smcavoy/lxd"
    COLL="$TMP/ansible_collections/smcavoy/lxd"
    ;;
esac
cd "$COLL" || exit 2
# A copied tree can have another owner. Mark it as safe for git in this process only.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="*"
if [ ! -d .git ]; then
  git init -q && git add -A
fi

status=0
step() {
  echo "=== $*"
  if ! "$@"; then
    echo "=== FAILED: $*"
    status=1
  fi
}

if [ "${SKIP_NOX:-}" != "1" ]; then
  step "$NOX" -e lint docs-check license-check extra-checks build-import-check
fi

# The nox lint session checks the collection code only. The CI code in ci/ and tests/lxd/lxdtest gets its own check.
TOOLS="$(mktemp -d)"
trap 'rm -rf "$TOOLS"; [ -n "${TMP:-}" ] && rm -rf "$TMP"' EXIT
if [ "${SKIP_TOOL_LINT:-}" != "1" ]; then
  python3 -m venv "$TOOLS/lint" && "$TOOLS/lint/bin/pip" install -q -r ci/requirements-fast.txt
  step "$TOOLS/lint/bin/ruff" check ci tests/lxd/lxdtest
  step env MYPYPATH=ci "$TOOLS/lint/bin/mypy" --config-file .mypy.ini ci/lxd_remote.py ci/bootstrap.py
  step "$TOOLS/lint/bin/mypy" --config-file .mypy.ini --platform linux --scripts-are-modules tests/lxd/lxdtest
  # Every changelog fragment must be valid. Each fix gets a fragment in changelogs/fragments.
  step "$TOOLS/lint/bin/antsibull-changelog" lint
fi

# Sanity and unit tests for each ansible-core version, each in its own venv. No Docker is needed.
if [ -z "${CI_CORES:-}" ]; then
  case "$CI_PYTHON" in
    3.11) CI_CORES="2.19" ;;
    3.12) CI_CORES="2.19 2.21" ;;
    *) CI_CORES="2.19 2.22" ;;
  esac
fi
for core in $CI_CORES; do
  echo "=== Sanity and unit tests with ansible-core $core on Python $CI_PYTHON."
  venv="$TOOLS/core-$core"
  if ! { python3 -m venv "$venv" && "$venv/bin/pip" install -q "ansible-core==$core.*"; }; then
    echo "=== FAILED: install ansible-core $core"
    status=1
    continue
  fi
  step "$venv/bin/ansible-test" sanity --venv --python "$CI_PYTHON" --color no
  step "$venv/bin/ansible-test" units --venv --python "$CI_PYTHON" --color no
done
exit "$status"
