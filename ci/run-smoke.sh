#!/usr/bin/env bash
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Optional smoke set for pull requests: a few standalone tests on one slot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE="${LXD_SMOKE_TESTS:-SC-WEB SC-ACCESS}"
# shellcheck disable=SC2086
exec python3 "$ROOT/ci/lxd_remote.py" --slots 1 $SMOKE
