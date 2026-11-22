<!--
Copyright (c) 2026, Sean McAvoy
GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Security policy

## Supported versions

Security fixes go into the newest release of `smcavoy.lxd`.

## Report a vulnerability

Do not open a public issue for a security problem.

Use the private report form of this repository on GitHub: the **Security** tab, then **Report a vulnerability**
(<https://github.com/smcavoy/ansible-modules-lxd/security/advisories/new>). Give the version of the collection, the
version of LXD and of ansible-core, the task that shows the problem, and what you saw.

You get an answer in the report. When a fix is released, the changelog names it under "Security Fixes".

The modules handle secrets: client keys, trust and join tokens, bucket keys, passwords in server config. A value of
that kind in a task result, a diff or a log is a security problem. Report it this way.
