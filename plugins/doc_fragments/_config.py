# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this doc fragment is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

from __future__ import annotations


class ModuleDocFragment:
    DOCUMENTATION = r"""
options:
  config:
    description:
      - Config keys and values.
      - The module converts numbers and booleans to strings, as LXD stores them.
      - A value of V(null) or an empty string removes the key.
      - If not set, the module does not manage the config.
    type: dict
  config_mode:
    description:
      - How to treat config keys that are on the server but not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them, except keys that LXD computes.
    default: merge
"""

    DEVICES = r"""
options:
  devices:
    description:
      - Devices by name. Each device is a dictionary of properties with the key V(type).
      - The module converts property values to strings. It compares each device as a whole.
      - A device value of V(null) removes the device.
      - If not set, the module does not manage the devices.
    type: dict
  devices_mode:
    description:
      - How to treat devices that are on the server but not in O(devices).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
"""
