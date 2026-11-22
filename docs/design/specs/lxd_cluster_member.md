# lxd_cluster_member

## 1. Purpose

Manage the roles, groups, failure domain, config, and description of a cluster member, and evacuate or restore it.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/cluster/members/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/cluster/members/{name}` | `PUT` | sync, checks `If-Match` | Update the member fields. |
| `/1.0/cluster/members/{name}/state` | `POST` | async | `evacuate` or `restore`. |
| `/1.0/cluster/members/{name}` | `DELETE` | sync | Remove the member. |

Required API extensions: `clustering_roles`, `clustering_failure_domains`, `clustering_description`, `clustering_config`, `clustering_groups`.
`evacuated` needs `clustering_evacuation`. `mode` needs `clustering_evacuation_mode`. `force` needs `clustering_evacuation_force`.

## 3. Identity

`name`, the member name.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The member name. |
| `state` | str | `present` | no | `present`, `evacuated`, or `absent`. |
| `roles` | list | | no | Roles to set: `control-plane` and `ovn-chassis`. `null` means "do not manage". |
| `groups` | list | | no | Cluster group names. `null` means "do not manage". |
| `failure_domain` | str | | no | `null` means "do not manage". |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Member config, for example `scheduler.instance` and `user.*`. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `evacuate_mode` | str | | no | With `evacuated`. `auto`, `live-migrate`, `migrate`, or `stop`. For `auto` the module sends no mode: LXD 6.10.1 has no mode of that name. |
| `restore_mode` | str | | no | With `present` on an evacuated member. `skip` restores the status but leaves instances where they are. |
| `force` | bool | `false` | no | With `evacuated`, skip the raft quorum check. With `absent`, remove a member that does not answer. |

## 5. Computed keys

The roles whose names start with `database` (LXD 6.10.1: `database-voter`, `database-standby`, `database-leader`). LXD assigns them. The module never adds or removes them.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| The member does not exist | Fail. Members join with `lxd_cluster`. |
| Same | No request. `changed: false`. |
| Fields differ | `PUT` with the full member. |
| Status `Evacuated` | `POST .../state` with `action: restore` and `mode` from `restore_mode`. |

### `evacuated`

| Case | Action |
|---|---|
| Status `Evacuated` | No state request. Fields still apply. |
| Otherwise | Apply fields. Then `POST .../state` with `action: evacuate`, `mode` from `evacuate_mode`, and `force`. |

### `absent`

| Case | Action |
|---|---|
| Not a member | No request. `changed: false`. |
| Member | `DELETE`, with `?force=1` if `force` is true. |

The module compares `roles` and `groups` as sets. It leaves out automatic roles from the compare.

## 7. Check and diff mode

The diff holds `roles`, `groups`, `failure_domain`, `description`, `config`, and `status`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `member` | dict | The member from `GET`, after the change. `null` after a delete. |

```yaml
member:
  server_name: cls-ab12-3
  url: https://10.0.0.33:8443
  status: Evacuated
  message: Unavailable due to maintenance
  roles:
    - database
    - ovn-chassis
  groups:
    - default
  failure_domain: default
  description: ""
  config: {}
```

## 9. Errors

| Case | Message |
|---|---|
| The member does not exist with `present`. | `cluster member <name> not found` |
| A role that is not valid. | The LXD error `Invalid cluster role ...` |
| An automatic role in `roles`. | `role <role> is assigned by LXD and cannot be set` |
| Evacuate before networks or pools start. | The LXD error `Cannot evacuate ... because some networks have not started yet` |

## 10. Cluster behavior

This module needs a cluster. On a standalone server, it fails with `This server is not clustered`.

## 11. Tests

Fixture: `lxd/cluster`. Standard cases C4 to C9 with `user.*` keys. CM1 to CM5.
Skip C1 to C3 and C10 to C12, because members join through `lxd_cluster`.

| ID | Goal | Pass when |
|---|---|---|
| CM1 | `evacuated` moves a running container. | The container runs on another member. Status `Evacuated`. |
| CM2 | `present` restores the member. | Status `Online`. The container moves back. |
| CM3 | `restore_mode: skip` leaves the container where it is. | The container stays on the other member. |
| CM4 | `roles: [ovn-chassis]` keeps the `database-*` roles. | `roles` holds both. |
| CM5 | `groups` adds the member to a test group. | The group lists the member. |

A test measured evacuate at 4.8 seconds and restore at 6.3 seconds.

## 12. Hardware exceptions

`evacuate_mode: live-migrate` for VMs needs nested VMs inside the cluster members. Mark that case `lxd/needs/vm` and run it each night.

## 13. Open questions

1. Should `absent` live here or only in `lxd_cluster`? This spec has both, with the same request.
