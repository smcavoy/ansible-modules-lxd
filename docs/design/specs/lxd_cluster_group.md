# lxd_cluster_group

## 1. Purpose

Create, update, and delete cluster groups, which place instances on a set of members.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/cluster/groups/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/cluster/groups` | `POST` | sync `201` | Create. |
| `/1.0/cluster/groups/{name}` | `PUT` | sync, ignores `If-Match` | Update `description` and `members`. |
| `/1.0/cluster/groups/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `clustering_groups`.

## 3. Identity

`name`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The group name. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `members` | list | | no | Member names. `null` means "do not manage". |
| `members_mode` | str | `exact` | no | `exact` sets the list. `merge` adds members and keeps the others. |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/cluster/groups` with `name`, `description`, and `members`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `description` and `members`. Rule R3 says that the server does not check `If-Match`. |

The module compares `members` as a set. LXD adds each new member to the `default` group on join.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present, empty | `DELETE`. |
| Present, with members | `PUT` with `members: []`, then `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `members`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `group` | dict | The group from `GET`, after the change. `null` after a delete. |

```yaml
group:
  name: gpu-nodes
  description: Members with GPUs
  members:
    - cls-ab12-2
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| Delete the `default` group. | The LXD error `The 'default' cluster group cannot be deleted` |
| Delete a group in use by a project or an instance. | The LXD error `Cluster group is currently in use` |
| A member that does not exist. | The LXD error. |

## 10. Cluster behavior

This module needs a cluster. On a standalone server, it fails with `This server is not clustered`.

## 11. Tests

Fixture: `lxd/cluster`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because groups have no config.

| ID | Goal | Pass when |
|---|---|---|
| CG1 | An instance with `target: @<group>` lands on a group member. | `location` is in `members`. |
| CG2 | `absent` on a group with members works. | The group is gone. |
| CG3 | Members in another order make no change. | `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. `absent` empties a group before the delete. Is that the right default, or should it fail? This spec empties it.
2. Should `members_mode` default to `exact`, as here, or to `merge`, like `config_mode`? `lxd_auth_group` asks the same question for `permissions_mode`.
