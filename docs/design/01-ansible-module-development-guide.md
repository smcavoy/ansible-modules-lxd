# Ansible module development guide for agents

Status: reference.
Audience: agents and people who write modules for the LXD collection.

## 1. Purpose

This guide tells you how to write an Ansible module in the current style.
It covers policy, file layout, documentation, code, behavior, and tests.
Follow it for every module in the LXD collection.

The rules come from these sources, read on 2026-11-02:

| Source | What it gives |
|---|---|
| ansible-documentation, `dev_guide/` | Official module rules: format, docs, best practices, checklist, tests. |
| ansible-documentation, `community/ai_policy.rst` | The Ansible AI policy. |
| community.general `AGENTS.md` and `CONTRIBUTING.md` | The strictest current rules for agents. Version 14.1.0 on the development branch. |
| community.general modules from 12.x to 14.x | Current code style, for example `logrotate`, `lxd_storage_volume_info`. |
| community.docker | The best model for a large set of API modules with shared connection options. |
| ansible-core devel 2.23 | The `module_utils` helpers and the `ansible-test` behavior. |

If two sources disagree, use the stricter rule.

## 2. Decisions for this collection

These are assumptions. Change them in one place if the maintainer decides differently.

| Item | Value |
|---|---|
| Collection name | `smcavoy.lxd` |
| License | GPL-3.0-or-later for all code. |
| Minimum ansible-core | 2.19 (`requires_ansible: '>=2.19.0'`). |
| Python on the module side | 3.10 or newer. Use no feature newer than 3.10. |
| Python on the controller | 3.11 or newer. ansible-core 2.19 supports 3.11 to 3.13 on the controller. |
| External Python libraries | None. Use only the standard library and `ansible.module_utils`. |
| LXD server | 6.10.1 or newer. |
| Version for new modules | `1.0.0` until the first release. Then read `galaxy.yml`. |

## 3. AI use policy

The Ansible community lets contributors use AI tools.
The policy applies to all repositories in the Ansible GitHub organizations.
community.general repeats the same rules.

Obey these rules:

1. You may use AI tools. A person stays fully responsible for each contribution.
2. AI output must obey all project rules, the code of conduct, and the license.
3. Maintainers can reject autonomous AI contributions without a reason.
4. Disclose AI use when a large part comes from AI output without large changes.
5. Grammar, spelling, and style fixes need no disclosure.
6. In commits, add a trailer. The policy recommends `Assisted-by:` and the tool name. Example: `Assisted-by: <tool name>`.
7. In issues, pull requests, and comments, add a short note that AI helped.

Rules for agents in this project:

- A person reviews and approves each change before it goes to an Ansible organization repository.
- Never open an issue or pull request upstream without a person's approval.
- Never mention a user with `@` in a commit message.
- Put the `Assisted-by:` trailer on every commit that contains AI-written code.

## 4. Collection layout

```text
ansible_collections/smcavoy/lxd/
  galaxy.yml
  meta/runtime.yml              # requires_ansible, action_groups
  plugins/
    modules/                    # one file per module
    module_utils/               # shared Python code, private names start with _
    doc_fragments/              # shared option documentation
    inventory/                  # optional, later
    connection/                 # optional, later
  tests/
    sanity/ignore-2.19.txt      # keep empty if possible
    unit/plugins/modules/
    unit/plugins/module_utils/
    integration/targets/<module_name>/
    integration/integration_config.yml   # local only, not in git
  changelogs/fragments/
  docs/docsite/rst/
  LICENSES/  REUSE.toml  README.md
```

Rules:

- Use one file per module. The file name is the module name.
- Use underscores in names. Hyphens and spaces stop the import.
- Start private `module_utils` and `doc_fragments` file names with `_`.
- Put code that two or more modules use in `module_utils`.
- Put option docs that two or more modules use in a doc fragment.

## 5. Module file structure

Every module file has these parts, in this order:

1. The shebang line `#!/usr/bin/python`. Do not use `/usr/bin/env`.
2. The copyright and license lines.
3. `from __future__ import annotations`.
4. The `DOCUMENTATION` string.
5. The `EXAMPLES` string.
6. The `RETURN` string.
7. The imports.
8. The `if t.TYPE_CHECKING:` block for type-only imports.
9. The classes and functions.
10. `get_argument_spec()`.
11. `main()`.
12. `if __name__ == "__main__": main()`.

Do not add a `# -*- coding: utf-8 -*-` line.
Do not put code or constants before the imports.
Separate the three documentation strings with one blank line.

Header template:

```python
#!/usr/bin/python
# Copyright (c) 2026, First Last (@githubid) <email@example.com>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
```

Use the current year in a new copyright line.
Do not change the year in an existing line.

## 6. Documentation strings

### 6.1 DOCUMENTATION

Required keys, in this order:

| Key | Rule |
|---|---|
| `module` | Same as the file name. |
| `short_description` | One line, no period at the end. Put it first after `module`. |
| `version_added` | A quoted string with the collection version. |
| `description` | A list of full sentences. Do not use the module name. |
| `author` | `First Last (@githubid)`. |
| `requirements` | Server and library minimums, for example `LXD 6.10.1 or newer`. |
| `extends_documentation_fragment` | The shared fragments. |
| `attributes` | `check_mode`, `diff_mode`, and `action_group`. |
| `options` | Every option in the argument spec. |
| `notes` | Only if necessary. |
| `seealso` | Links to related modules and LXD documentation. |

Rules for each option:

- Write each `description` as a list of full paragraphs.
- Do not split one sentence over two list items.
- Make the first paragraph say what the option is.
- Put `type` on every option. Put `elements` on every list.
- Make `type`, `default`, and `choices` match the argument spec exactly.
- Do not write the default in the description.
- Do not list the choices in the description.
- To explain each choice, make `choices` a dictionary of value to description.
- Describe a boolean by what happens when it is `true`.
- Write booleans as `true` and `false`.
- Say when the user must set an option. Example: "Required when O(state=present)."
- Put the mutual exclusion sentence last in each affected option.
- Do not add aliases unless they are strictly necessary.
- Use current LXD names. Do not use legacy names.
- State behavior that is not clear to people who do not know Python.

Use semantic markup:

| Markup | Use |
|---|---|
| `O(name)` | An option. `O(state=present)` for an option with a value. |
| `V(value)` | A value. |
| `RV(name)` | A return value. |
| `C(text)` | Code, commands, paths. |
| `E(NAME)` | An environment variable. |
| `M(fqcn)` | Another module. |
| `U(url)` and `L(text,url)` | Links. |

Do not use the old markup `I()` and `B()` for options or values.

Attributes template for a module that changes state:

```yaml
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
```

Attributes for an info module:

```yaml
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
```

The `action_group` fragment part sets `support: full` and `membership: [smcavoy.lxd.lxd]`.
community.docker uses the same pattern in `_attributes.py`.

Set `support: full` only if every code path honors the attribute.
Otherwise set `support: partial` and explain the gap in `details`.
Do not put check mode or diff mode text in `notes`.

### 6.2 EXAMPLES

- Give each task a `name:` that starts with a capital letter and has no period.
- Use the full collection name, for example `smcavoy.lxd.lxd_network`.
- Use `true` and `false` for booleans.
- Keep lines short. Move long values into `vars:` or YAML folded scalars.
- Put example secrets in values that start with `EXAMPLE`.
- Show the common cases first: create, change, remove.
- Copy each example into an integration test, so the examples stay correct.

### 6.3 RETURN

- Document every key that the module returns, except the standard keys.
- Give `description`, `returned`, `type`, and `sample` for each key.
- Use `contains` for nested dictionaries and lists of dictionaries.
- If the module returns nothing extra, write `RETURN = r""" # """`.

## 7. Code style

### 7.1 Formatting and type checks

- Format with `ruff format`. Check with `ruff check`.
- Sort imports with ruff rule `I`.
- Check types with `mypy`.
- Run these through `antsibull-nox`, like community.general.

### 7.2 Imports

- Import the standard library first, then `ansible.module_utils`, then collection code.
- Do not use wildcard imports.
- Import collection code by its full path:

```python
from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClient
```

- The collection uses no external Python library. If one is ever necessary, use `missing_required_lib()`.

### 7.3 Type hints

- Use `import typing as t`. Do not use `from typing import ...`.
- Write `X | None`. Do not write `t.Optional[X]`.
- Do not use `t.Any` for third-party objects.
- Put type-only imports inside `if t.TYPE_CHECKING:  # pragma: no cover`.
- Build the argument spec in `get_argument_spec() -> ArgumentSpecT`.
- Type the result as a `TypedDict`.
- Copy the typing helpers from community.general `plugins/module_utils/_typing.py`.

### 7.4 Parameters

- Read parameters as `module.params["name"]`. Do not use `.get()`.
- Every option in the spec is always present. Its value is `None` if not set.
- Give a fallback with `default` in the spec, not in the code.
- Put constraints in the spec: `required_if`, `required_together`, `required_one_of`, `required_by`, `mutually_exclusive`.
- Check in code only what the spec cannot express.
- Set `no_log=True` on secrets.
- Set `no_log=False` on options with names like `password_length` that hold no secret.
- Use `env_fallback` only for connection options. Use the prefix `LXD_`.
- Name the environment variable in the option description, for example `E(LXD_URL)`.

### 7.5 Names and small rules

- Use underscores in function names. Give each function a docstring.
- Do not start names with `_` in module files.
- Compile regular expressions once, outside loops.
- Use `collections.abc.Mapping` and `Sequence` to check user data, not `dict` and `list`.
- Do not convert a value to a type that it already has.
- Write `if changed:`, not `if changed == True:`.
- Do not write comments that only repeat the code.
- Put repeated code, for example URL building, into one function.
- Keep functions short. Move deep loop bodies into functions.

### 7.6 Execution and I/O

- Never print to stdout or stderr. Return data only through `exit_json` and `fail_json`.
- Never call `sys.exit()`.
- Use `module.run_command()` for commands. Do not use `subprocess` or `os.system`.
- Do not use a shell unless it is necessary.
- Use `ansible.module_utils.urls` for HTTP. It supports Unix sockets and client certificates.
- Do not use `urllib` directly.
- Do not use `requests`.
- Write files with a temporary file and `module.atomic_move()`.
- Do not create caches.

## 8. Module behavior

### 8.1 Scope

- Each module does one thing well.
- If an API is large, write many small modules, one for each resource.
- Do not add `state: info` or `state: list`. Write a separate `_info` module.
- A module must not call other modules. Use a role for that.
- Name the option for the managed object `name`.
- Do not use `action` or `command` options. They are not declarative.

### 8.2 States

- Use states that describe the result: `present`, `absent`, `started`, `stopped`.
- Do not use states that describe a command: `create`, `delete`, `start`.
- Make the module idempotent. A second run with the same input reports no change.
- If a resource cannot be idempotent, document the reason.
- A state that runs an action on each run, such as `restarted`, always reports a change. Say so in the state description.

### 8.3 The changed flag

- Compare the requested state with the current state. Set `changed` from that comparison.
- Do not set `changed=true` only because the module sent a request.
- Normalize values before you compare them. Examples: `None` and `""`, `"1GiB"` and `1073741824`.

### 8.4 Check mode

- In check mode, change nothing.
- In check mode, return the same `changed` value that a real run returns.
- Do not return a fixed `changed` value in check mode.
- Info modules must support check mode.

### 8.5 Diff mode

- In diff mode, return `diff` with `before` and `after`.
- Use dictionaries for `before` and `after` when the resource has structure.
- Remove volatile and server-generated keys from the diff.

### 8.6 Input handling

- Reject contradictory or meaningless option combinations.
- Never transform, discard, or ignore user input without a message.
- If the module cannot apply the input, fail with a clear message.
- If a lenient mode is useful, make it an option with `fail` as the default.
- If an operation needs an object that does not exist, fail.
- If the module must make an assumption, warn with `module.warn()`.
- Pass on server warnings and errors. Do not copy the server's checks into the module.
- Do not add options or safety checks that nobody asked for.

### 8.7 Errors and messages

- Validate early. Fail fast with a clear `msg`.
- Do not let a traceback escape. Catch the client exception and call `fail_json`.
- Do not catch all exceptions without a reason.
- Say what the module tried to do, then add the server message.
- Keep messages neutral and accurate. Write "Network not found", not "Network deleted or does not exist".

### 8.8 Return values

- Return a dictionary at the top level.
- Return useful data even when nothing changes.
- Return the same keys on every run. Use `None` when a value does not apply.
- Return only plain JSON types: `str`, `int`, `float`, `bool`, `list`, `dict`, `None`.
- Do not return large blobs, for example full logs.
- Return the resource in its server form after the change. Use one key, named after the resource.

### 8.9 Info and facts modules

- Name a read-only module `<resource>_info`. Use the singular form.
- An info module changes nothing and supports check mode.
- An info module returns its data in the result, not in `ansible_facts`.
- An info module returns a list under the plural resource key, for example `networks`.
- A `name` that does not exist gives an empty list. The module does not fail.
- Use `_facts` only for data about the managed host itself. LXD modules do not need `_facts`.

### 8.10 Deprecation

- Do not deprecate as a side effect of other work.
- Plan removal two major versions later.
- For an option with no default, use `removed_in_version` and `removed_from_collection`.
- For an option with a default, remove the default from the spec. Detect `None` in code, then call `module.deprecate()`.
- Prefer additive changes, such as a new choice, over a changed default.

## 9. Shared code for a family of API modules

community.docker shows the best pattern for a large API collection.
Use these parts:

1. A doc fragment `_connection.py` that documents the connection options once.
2. A `module_utils/_client.py` with the HTTP client and the connection argument spec.
3. An action group `lxd` in `meta/runtime.yml` that lists every module.
4. The `action_group` part of the `_attributes` doc fragment.
5. A base class that loads the connection options and builds the client.

With the action group, a user sets the connection once:

```yaml
- hosts: localhost
  module_defaults:
    group/smcavoy.lxd.lxd:
      url: https://lxd01.example.com:8443
      client_cert: ~/.config/lxc/client.crt
      client_key: ~/.config/lxc/client.key
  tasks:
    - smcavoy.lxd.lxd_network:
        name: lxdbr1
```

Add each new module to the action group.
The `antsibull-nox` `action_groups` check finds a missing module.

## 10. Testing

Every module needs sanity tests, unit tests, and integration tests.

The scripts in `ci/` run the same checks as the CI jobs:

| Command | Checks |
|---|---|
| `ci/run-fast.sh` | Lint, types, docs, licenses, build, sanity, and unit tests. |
| `ci/run-lxd.sh --all` | All integration targets and scenarios on the test server. |
| `ci/run-smoke.sh` | A small set of scenarios. |

### 10.1 Sanity tests

```bash
ansible-test sanity --docker default --python 3.13 plugins/modules/lxd_network.py
```

Run `ansible-test` from the newest ansible-core release.
Give `--python` a version that this release supports on the controller.
Python 3.13 works with ansible-core 2.19 and with the development branch.

Sanity tests check documentation, the argument spec, imports, PEP 8, YAML, and more.
`validate-modules` compares `DOCUMENTATION` with the argument spec.
Fix every error. Do not add lines to `tests/sanity/ignore-*.txt`.

### 10.2 Unit tests

```bash
ansible-test units --docker default --python 3.13 tests/unit/plugins/modules/test_lxd_network.py
```

Rules:

- Write pytest functions, not test classes. Use fixtures.
- Mock with `mocker`. Do not patch `sys.modules`.
- Mock all HTTP calls. Run the real module and catch `SystemExit`.
- Never mock the whole module.
- Test the happy paths: change, no change, partial change.
- Test the error paths.
- Test that check mode sends no write request.
- Do not test Ansible features, such as `mutually_exclusive`.
- Do not test static data, such as the argument spec.
- Use `set_module_args` from `community.internal_test_tools`. Import it from `ansible_collections.community.internal_test_tools.tests.unit.plugins.modules.utils`.

### 10.3 Integration tests

Each target in `tests/integration/targets/` is like a role.
It has an `aliases` file and `tasks/main.yml`.
A target with a name that starts with `setup_` is a setup target.
Other targets list setup targets in `meta/main.yml` under `dependencies`.

Rules:

- Test against a real LXD server.
- Test as a black box. Give inputs. Then examine the outputs.
- Run each change twice. Check that the second run reports no change.
- Change one attribute of an existing resource. Check the change.
- Run each change in check mode first. Check that nothing changed on the server.
- Check only the values that the test changed.
- Test an error path with `ignore_errors: true` and `register`. Then check `is failed` and the `msg`.
- Use full collection names everywhere, also for lookups and filters.
- Give each registered variable a distinct, descriptive name.
- Split large tests into files and use `ansible.builtin.include_tasks`.
- Clean up every resource in an `always:` block.
- Keep downloads and disk use small.

The testing framework document gives the LXD rules for targets, aliases, and parallel runs.

Integration tests use `ansible-core` `2.20.11` on Python `3.14` in the runner.
Integration tests connect to LXD by host name. LXD server certificates do not hold the server IP address.

## 11. Changelog and release

- Do not add a changelog fragment for a new module.
- Add a fragment for every change to an existing module or shared code that users can see.
- Name it `changelogs/fragments/<PR number>-<short-name>.yml`.
- Use the keys `minor_changes`, `bugfixes`, `breaking_changes`, `deprecated_features`, `removed_features`.
- Write one short sentence per entry, in lower case, from the user's view.
- Add the issue URL and the PR URL to each entry.
- Use semantic versioning. Keep backward compatibility.
- Put `version_added` on a new option or return value in an existing module.
- For a new choice or alias, add a sentence to the description instead.

## 12. Licensing

- Follow the REUSE specification.
- Put the license lines at the top of every file, after the shebang.
- If a file cannot hold comments, put the lines in `<file>.license`.
- Check with `nox -e license-check`.

## 13. Old styles that you must not copy

Old modules and old guides show these patterns. Do not copy them.

| Old style | Current style |
|---|---|
| `module.params.get("x")` | `module.params["x"]` |
| `from typing import Optional` | `import typing as t` and `X \| None` |
| Argument spec inline in `main()` | `get_argument_spec() -> ArgumentSpecT` |
| `# -*- coding: utf-8 -*-` | No encoding line. |
| `__metaclass__ = type` and `from __future__ import absolute_import, division, print_function` | `from __future__ import annotations` only. |
| `I()` and `B()` markup for options | `O()` and `V()`. |
| Choices explained in the description | `choices` as a dictionary. |
| `check_mode` in `notes` | `attributes`. |
| `state: list` or `state: info` | A separate `_info` module. |
| `changed=True` after every write | Compare before and after. |
| `requests` or `urllib` | `ansible.module_utils.urls`. |
| Handwritten `http.client` Unix socket class | `Request(unix_socket=...)`. |
| `%` or `.format()` strings | f-strings. |
| `yes` and `no` in docs and examples | `true` and `false`. |
| Short module names in examples | Full collection names. |
| LXD `trust_password` option | Trust tokens or a client certificate. LXD 6 has no trust password. |

The existing community.general LXD modules show several of these old patterns.
Use them to learn the LXD API, not to copy style.

## 14. Checklist for each module

Use this list before you ask for review.

- [ ] The file follows the part order in section 5.
- [ ] `DOCUMENTATION`, `EXAMPLES`, and `RETURN` hold every key and use semantic markup.
- [ ] The argument spec matches the docs. `validate-modules` passes.
- [ ] Constraints are in the argument spec.
- [ ] The module uses the shared client and connection fragment.
- [ ] The module is in the `lxd` action group.
- [ ] `changed` comes from a comparison.
- [ ] Check mode sends no write request and predicts `changed` correctly.
- [ ] Diff mode returns `before` and `after`.
- [ ] Errors give a clear `msg` and no traceback.
- [ ] Sanity tests pass.
- [ ] Unit tests cover change, no change, check mode, and errors.
- [ ] The integration test covers create, idempotency, update, check mode, error, and delete.
- [ ] The integration test cleans up in `always:`.
- [ ] The commit has the `Assisted-by:` trailer if AI wrote a large part.
