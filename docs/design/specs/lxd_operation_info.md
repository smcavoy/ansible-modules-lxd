# lxd_operation_info

## 1. Purpose

Read LXD operations, for example to find running tasks before maintenance.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/operations?recursion=1` | `GET` | Operations in the project. With `?all-projects=true`, in all projects. |
| `/1.0/operations/{id}` | `GET` | One operation. |

Required API extensions: none. With `all_projects`: `operations_get_query_all_projects`.

## 3. Identity

`id`, if set.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `id` | str | | no | One operation. A missing ID gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Operations in all projects. Mutually exclusive with `project`. |
| `status` | list | | no | Keep only these statuses, for example `Running`. The module filters on the client. |
| `class` | str | | no | Keep only `task`, `websocket`, or `token`. |

Token operations hold secrets in `metadata`. The module removes `metadata.secret` and `metadata.secrets` from every item.

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `operations` | list | Each item is an operation object without secrets. |

```yaml
operations:
  - id: 01a1a00a-6ae7-7412-8972-aea8529f209b
    class: task
    description: Creating instance
    status: Running
    status_code: 103
    resources:
      instances:
        - /1.0/instances/web1
    may_cancel: false
    err: ""
    location: none
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

Each item has `location`. LXD lists the operations of all members.

## 11. Tests

Fixture: `lxd/standalone`. I1 to I4, with `id` for I2 and I3.

| ID | Goal | Pass when |
|---|---|---|
| OP1 | A trust token operation has no secret in the result. | No item has `metadata.secret`. |
| OP2 | `class: token` lists only token operations. | Every item has `class: token`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
