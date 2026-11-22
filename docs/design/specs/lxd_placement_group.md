# lxd_placement_group

## 1. Purpose

Create, update, and delete placement groups that spread instances across members or keep them together.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/placement-groups/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/placement-groups` | `POST` | sync `201` | Create. |
| `/1.0/placement-groups/{name}` | `PUT` | sync, checks `If-Match` | Update `description` and `config`. |
| `/1.0/placement-groups/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `instance_placement_groups`.

## 3. Identity

`name` and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The group name. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `policy` | str | | yes for create | `spread` or `compact`. The module sends it as `config.policy`. |
| `rigor` | str | | yes for create | `strict` or `permissive`. The module sends it as `config.rigor`. |
| `config` | dict | | no | Rule R4. Only `user.*` keys. |
| `config_mode` | str | `merge` | no | Rule R4. `exact` never removes `policy` and `rigor`. |

`policy` and `rigor` are config keys in the API. The module gives them their own options, because LXD requires them.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST` with `name`, `description`, and `config` with `policy` and `rigor`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

An instance uses the group through its config key `placement.group`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `policy`, `rigor`, and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `placement_group` | dict | The group from `GET`, after the change. `null` after a delete. |

```yaml
placement_group:
  name: web-spread
  project: default
  description: ""
  config:
    policy: spread
    rigor: strict
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| The server is not clustered. | The LXD error `This server is not clustered` |
| Create without `policy` or `rigor`. | `policy and rigor are required to create a placement group` |
| Delete a group in use. | The LXD error `Placement group ... is currently in use` |

## 10. Cluster behavior

This module needs a cluster.

## 11. Tests

Fixture: `lxd/cluster`. Standard cases C1 to C12. C6 to C8 use `user.*` keys.

| ID | Goal | Pass when |
|---|---|---|
| PG1 | `spread` with `strict` puts 3 instances on 3 members. | Each instance has a different `location`. |
| PG2 | `compact` puts 2 instances on one member. | Both have the same `location`. |
| PG3 | A fourth instance with `spread` and `strict` fails on 3 members. | The create fails with the LXD placement error. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. PG3 assumes that `strict` spread allows one instance per member. Confirm this in the first test run. The source confirms the key name `placement.group`.
