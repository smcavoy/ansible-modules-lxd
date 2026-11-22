# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this doc fragment is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

from __future__ import annotations


class ModuleDocFragment:
    # Standard attributes
    DOCUMENTATION = r"""
options: {}
attributes:
  check_mode:
    description: Can run in C(check_mode) and return changed status prediction without modifying target.
  diff_mode:
    description: Will return details on what has changed (or possibly needs changing in C(check_mode)), when in diff mode.
  idempotent:
    description:
      - When run twice in a row outside check mode, with the same arguments, the second invocation indicates no change.
      - This assumes that the system controlled/queried by the module has not changed in a relevant way.
"""

    # Use together with the standard fragment
    INFO_MODULE = r"""
options: {}
attributes:
  check_mode:
    support: full
    details:
      - This action does not modify state.
  diff_mode:
    support: N/A
    details:
      - This action does not modify state.
  idempotent:
    support: full
    details:
      - This action does not modify state.
"""

    ACTION_GROUP = r"""
options: {}
attributes:
  action_group:
    description: Use C(group/smcavoy.lxd.lxd) in C(module_defaults) to set defaults for this module.
    support: full
    membership:
      - smcavoy.lxd.lxd
"""
