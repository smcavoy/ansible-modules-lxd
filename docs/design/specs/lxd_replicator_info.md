# lxd_replicator_info

## 1. Purpose

Read replicators with their last run and current status.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/replicators?recursion=1` | `GET` | All replicators in the project. With `?all-projects=true`, in all projects. |
| `/1.0/replicators/{name}` | `GET` | One replicator. |
| `/1.0/replicators/{name}/state` | `GET` | The current `status`. |

Required API extensions: `replicators`.

## 3. Identity

`name` and `project`, if set.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One replicator. A missing one gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Replicators in all projects. Mutually exclusive with `project`. |
| `include_state` | bool | `false` | no | Add `state.status`. One extra request per replicator. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `replicators` | list | Each item is a replicator object, with `state` on request. |

```yaml
replicators:
  - name: web-dr
    project: web
    config:
      cluster: dr-site
    last_run_status: Completed
    last_success_at: "2026-11-03T06:00:00Z"
    state:
      status: Completed
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/multicluster`. Standard cases I1 to I4.

## 12. Hardware exceptions

None.

## 13. Open questions

None.
