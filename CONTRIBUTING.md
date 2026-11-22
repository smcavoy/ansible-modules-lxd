<!--
Copyright (c) 2026, Sean McAvoy
GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing

Issues and pull requests are on GitHub: <https://github.com/smcavoy/ansible-modules-lxd>.
By taking part you agree to the `CODE_OF_CONDUCT.md`. For a security problem, read `SECURITY.md` first.

## Report a defect

Open an issue with:

- the version of the collection (`ansible-galaxy collection list smcavoy.lxd`), of ansible-core and of LXD
- the task, with secrets removed
- what you expected and what happened; the output with `-vvvv` shows each request to LXD in `http_log`

## Send a change

1. Fork the repository and make a branch.
2. Make the change. `AGENTS.md` describes the layout of the code and the rules: each fix has a test that fails on
   the old code, and each user-visible change has a changelog fragment in `changelogs/fragments/`.
3. Run the fast checks: `ci/run-fast.sh`. They need Python 3.11 or newer and no LXD server.
4. Open a pull request. Say what the change does and why, and how you tested it. GitHub Actions runs the fast
   checks on it.

The integration suite needs an LXD server and does not run on GitHub. The maintainer runs it on a test server
before a merge that changes modules or tests. If you ran integration targets on your own server, say which ones.

## Changelog fragments

A fragment is a small YAML file, for example `changelogs/fragments/123-instance-restart.yml`:

```yaml
bugfixes:
  - lxd_instance - a restart of a frozen instance now restarts it (https://github.com/smcavoy/ansible-modules-lxd/pull/123).
```

The sections are those of [antsibull-changelog](https://github.com/ansible-community/antsibull-changelog/blob/main/docs/changelogs.md):
`bugfixes`, `minor_changes`, `security_fixes`, `breaking_changes`, and others.

## License

Contributions are under the GNU General Public License v3.0 or later, as the rest of the collection.
