# shellcheck shell=sh
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build step 1 of the sandbox image. ci/bootstrap.py runs it in the build VM as root.
# LXD_CHANNEL is the snap channel, for example 6/stable.
# Every file in this folder is part of the image recipe. A change gives a new image name.
set -eu
cloud-init status --wait >/dev/null || true
snap wait system seed.loaded
if snap list lxd >/dev/null 2>&1; then
  snap refresh lxd --channel="$LXD_CHANNEL"
else
  snap install lxd --channel="$LXD_CHANNEL"
fi
snap refresh --hold lxd

# The MicroCloud fixture uses the snaps of the MicroCloud 3.4 LTS bundle: LXD 6, MicroCeph Tentacle, MicroOVN 26.03.
# Their services stay off in every sandbox. The first-boot unit starts them only in MicroCloud mode.
MICROCEPH_CHANNEL=tentacle/stable
MICROOVN_CHANNEL=26.03/stable
MICROCLOUD_CHANNEL=3/stable
snap install microceph --channel="$MICROCEPH_CHANNEL"
snap install microovn --channel="$MICROOVN_CHANNEL"
snap install microcloud --channel="$MICROCLOUD_CHANNEL"
snap refresh --hold microceph microovn microcloud
# The Ceph tools in the LXD 6.10 snap do not work with Ceph 19.2.6, 20.2.4, or newer. Stop the build before that breaks the tests.
ceph_version=$(snap list microceph | awk 'NR==2 {print $2}' | cut -d+ -f1)
case "$ceph_version" in
  19.2.[0-5] | 20.2.[0-3]) ;;
  *) echo "MicroCeph $ceph_version is not known to work with the LXD 6.10 snap" >&2; exit 1 ;;
esac
mkdir -p /etc/lxd-sandbox /usr/local/sbin
snap services microceph microovn microcloud | awk '$2 == "enabled" {print $1}' >/etc/lxd-sandbox/micro-services
xargs -r snap stop --disable </etc/lxd-sandbox/micro-services
