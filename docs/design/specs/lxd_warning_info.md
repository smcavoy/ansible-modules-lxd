# lxd_warning_info

## 1. Purpose

Read LXD warnings, filtered by project, status, or severity.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/warnings?recursion=1` | `GET` | Warnings. With `?project=`, only that project. With `?all-projects=true`, all. |
| `/1.0/warnings/{uuid}` | `GET` | One warning. |

Required API extensions: `warnings`.

## 3. Identity

`uuid`, if set.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `uuid` | str | | no | One warning. A missing UUID gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `true` | no | Warnings in all projects, including server warnings. A task that sets `project` turns it off. |
| `status` | list | | no | Keep only `new`, `acknowledged`, or `resolved`. |
| `severity` | list | | no | Keep only `low`, `moderate`, or `high`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `lxd_warnings` | list | Each item is a warning object. Not `warnings`: Ansible uses that key for task warnings. |

```yaml
lxd_warnings:
  - uuid: e9f1...
    type: Couldn't find the CGroup memory swap accounting
    severity: low
    status: new
    count: 1
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

Each item has `location`.

## 11. Tests

Fixture: `lxd/standalone`. I1, I3, and I4. I2 runs only if the sandbox has a warning.

## 12. Hardware exceptions

None.

## 13. Open questions

None. The source confirms the `severity` values.
