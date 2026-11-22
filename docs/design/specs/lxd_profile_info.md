# lxd_profile_info

## 1. Purpose

Read LXD profiles in a project.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/profiles?recursion=1` | `GET` | All profiles in the project. |
| `/1.0/profiles?recursion=1&all-projects=true` | `GET` | Profiles in all projects. Needs `profiles_all_projects`. |
| `/1.0/profiles/{name}` | `GET` | One profile. |

Required API extensions: none. With `all_projects`: `profiles_all_projects`.

## 3. Identity

`name` and `project`, if set. Without `name`, all profiles.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One profile. A missing profile gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Profiles in all projects. Mutually exclusive with `project` and `name`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `profiles` | list | Each item is a profile object with `project`. |

```yaml
profiles:
  - name: default
    project: default
    config: {}
    devices:
      root:
        type: disk
        path: /
        pool: default
    used_by: []
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| PRI1 | `all_projects` finds a profile in the test project. | The list holds the profile with the test project name. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
