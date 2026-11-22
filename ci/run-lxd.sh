#!/usr/bin/env bash
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tier 2: the full LXD suite on the test server, through the LXD API.
# Arguments go to ci/lxd_remote.py, for example --scenarios-only or target names.
# The environment variables are in the docstring of ci/lxd_remote.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/ci/lxd_remote.py" "$@"
