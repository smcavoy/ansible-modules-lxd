# lxd_project

## 1. Purpose

Create, update, and delete LXD projects, with their config, description, and replica mode.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/projects/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/projects` | `POST` | sync `201` | Create. |
| `/1.0/projects/{name}` | `PUT` | sync, checks `If-Match` | Update `config` and `description`. |
| `/1.0/projects/{name}` | `DELETE` | async | Delete. `?force=true` deletes all contents. |
| `/1.0/projects/{name}/state` | `PUT` | async | Set `replica_mode`. |

Required API extensions: `projects`. With `force_delete`: `projects_force_delete`.
With `replica_mode`: `project_replica_mode`. With `default_storage_pool` or `default_network`: `project_default_network_and_storage`.

## 3. Identity

`name`. The module does not rename projects.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The project name. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `default_storage_pool` | str | | no | Create-only. LXD adds a root disk on this pool to the new default profile. |
| `default_network` | str | | no | Create-only. LXD adds a NIC on this network to the new default profile. |
| `replica_mode` | str | | no | `leader`, `standby`, or `""` to clear. `null` means "do not manage". |
| `force_delete` | bool | `false` | no | With `state: absent`, delete the project and everything in it. |

## 5. Computed keys

`features.images`, `features.profiles`, `features.storage.volumes`, `features.storage.buckets`.
LXD sets these four keys to `true` on create when the request does not hold them.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/projects` with `name`, `description`, `config`, and the create-only options. Then set `replica_mode` if the task sets it. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. Set `replica_mode` with `PUT .../state` if it differs. |
| Create-only option differs | Ignore it. Warn `default_storage_pool and default_network apply only on create`. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. With `force_delete: true`, add `?force=true`. |

The `default` project cannot be deleted. The module fails before the request.

## 7. Check and diff mode

The diff holds `description`, `config`, and `replica_mode`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `project` | dict | The project from `GET`, after the change. `null` after a delete. |

```yaml
project:
  name: web
  description: Web servers
  config:
    features.images: "true"
    features.profiles: "true"
    features.storage.volumes: "true"
    features.storage.buckets: "true"
    limits.instances: "10"
  replica_mode: ""
  used_by:
    - /1.0/profiles/default?project=web
```

## 9. Errors

| Case | Message |
|---|---|
| Delete the `default` project. | `The default project cannot be deleted` |
| Delete a project that holds objects. | The LXD error `Only empty projects can be removed`. The module adds `Set force_delete to delete its contents.` |
| Change a feature on a project that holds objects. | The LXD error `Project feature ... cannot be enabled on non-empty projects` |
| Change a feature of the `default` project. | The LXD error `You cannot change the features of the default project` |
| Bad `replica_mode`. | Ansible `choices` error. |

## 10. Cluster behavior

None. Projects are global in a cluster. `replica_mode` needs a cluster link, but no `target`.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C12.

| ID | Goal | Pass when |
|---|---|---|
| P1 | `default_storage_pool` and `default_network` fill the default profile. | The profile of the new project has the root disk and the NIC. |
| P2 | A create-only option on an existing project gives a warning. | `changed` is false. `warnings` holds the text. |
| P3 | `force_delete` deletes a project with a profile and a volume. | The project is gone. |
| P4 | A delete without `force_delete` fails on a project with a volume. | `msg` holds `force_delete`. |
| P5 | The module refuses to delete `default`. | `msg` holds the expected text. No request is sent. |

`replica_mode` tests belong to the `lxd/multicluster` fixture, in the `lxd_replicator` target.

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `force_delete` also need `state: absent`, or should it be a separate choice `state: purged`? This spec uses an option.
