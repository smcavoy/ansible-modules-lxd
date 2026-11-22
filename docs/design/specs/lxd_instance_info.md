# lxd_instance_info

## 1. Purpose

Read LXD instances with their config, run state, and addresses.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/instances?recursion=2` | `GET` | All instances with state. With `filter`, the matching ones. |
| `/1.0/instances/{name}?recursion=1` | `GET` | One instance with state. |

Required API extensions: `instances`. With `all_projects`: `instance_all_projects`. With `filter`: `api_filtering`.

## 3. Identity

`name` and `project`, or `filter`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One instance. A missing instance gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Instances in all projects. Mutually exclusive with `project`. |
| `filter` | str | | no | An LXD filter, for example `status eq Running`. Mutually exclusive with `name`. |
| `include_state` | bool | `true` | no | Add `state`. With `false`, the module uses `recursion=1`, which is faster. |
| `include_snapshots` | bool | `false` | no | Add `snapshots`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `instances` | list | Each item is an instance object with `project`, `state`, and `addresses`. |

```yaml
instances:
  - name: web1
    project: default
    type: container
    status: Running
    location: none
    config:
      limits.cpu: "2"
    expanded_config:
      limits.cpu: "2"
    state:
      status: Running
    addresses:
      eth0:
        - 10.99.0.12
```

## 9. Errors

| Case | Message |
|---|---|
| A bad `filter`. | The LXD error `Invalid filter: ...` |

## 10. Cluster behavior

Each item has `location`. The module needs no `target`.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| INI1 | `filter: status eq Running` lists only running instances. | Every item has `status: Running`. |
| INI2 | `include_state: false` has no `state` key. | No item has `state`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
