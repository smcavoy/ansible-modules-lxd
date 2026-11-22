# lxd_project_info

## 1. Purpose

Read LXD projects, with their config and, on request, their resource usage.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/projects?recursion=1` | `GET` | All projects. |
| `/1.0/projects/{name}` | `GET` | One project. |
| `/1.0/projects/{name}/state` | `GET` | Usage and limits. Needs `project_usage`. |

Required API extensions: `projects`. With `include_state`: `project_usage`.

## 3. Identity

`name`, if set. Without `name`, all projects.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One project. A missing project gives an empty list. |
| `include_state` | bool | `false` | no | Add `state` to each project. One extra request per project. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `projects` | list | Each item is a project object. With `include_state`, each item has `state.resources`. |

```yaml
projects:
  - name: default
    description: Default LXD project
    config:
      features.images: "true"
    used_by: []
    state:
      resources:
        instances:
          limit: -1
          usage: 3
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| PI1 | `include_state` adds usage. | `state.resources.instances.Usage` is a number. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.

## 14. Findings from the tests

1. The project state returns the fields of each resource as `Limit` and `Usage`, with capital letters. The Go type has no JSON tags.
   A `Limit` of `-1` means no limit.
