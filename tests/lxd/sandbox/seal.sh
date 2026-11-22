# shellcheck shell=sh
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build step 2 of the sandbox image, after the first-boot files are in place.
# It enables the first-boot unit and clears the machine identity before the publish.
set -eu
systemctl enable lxd-sandbox-init.service
cloud-init clean --logs --machine-id
