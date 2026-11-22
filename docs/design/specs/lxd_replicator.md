# lxd_replicator

## 1. Purpose

Create, update, and delete replicators that copy the instances of a project to another cluster on a schedule.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/replicators/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/replicators` | `POST` | sync | Create. |
| `/1.0/replicators/{name}` | `PUT` | sync, checks `If-Match` | Update `description` and `config`. |
| `/1.0/replicators/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `replicators`. Custom volume replication needs `replicator_custom_volumes`.

## 3. Identity

`name` and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The replicator name. |
| `project` | str | | no | The source project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. `cluster` is required on create. Also `schedule` and `user.*`. |
| `config_mode` | str | `merge` | no | Rule R4. `exact` never removes `cluster`. |

`cluster` names a cluster link. `schedule` is a cron expression, for example `@daily` or `0 6 * * *`.
The project on the other cluster needs `replica_mode: standby`. Use `lxd_project` there.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST` with `name`, `description`, and `config`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `replicator` | dict | The replicator from `GET`, with `last_run_at` and `last_run_status`. `null` after a delete. |

```yaml
replicator:
  name: web-dr
  project: web
  description: ""
  config:
    cluster: dr-site
    schedule: "@daily"
  last_run_at: "2026-11-03T06:00:00Z"
  last_run_status: Completed
```

## 9. Errors

| Case | Message |
|---|---|
| Create without `config.cluster`. | `config.cluster is required to create a replicator` |
| The cluster link does not exist. | The LXD error. |
| A bad cron expression. | The LXD validation error. |

## 10. Cluster behavior

None beyond the cluster link.

## 11. Tests

Fixture: `lxd/multicluster`. Standard cases C1 to C12. C6 to C8 use `user.*` keys.
The test also sets `replica_mode: leader` on the source project and `standby` on the target project, with `lxd_project`.

| ID | Goal | Pass when |
|---|---|---|
| RP1 | `config_mode: exact` keeps `cluster`. | `cluster` stays. |
| RP2 | A replicator in a project with `replica_mode: leader`. | The create works. |

`lxd_replicator_run` covers the copy itself.

## 12. Hardware exceptions

Ceph RBD mirroring needs two Ceph clusters. Section 13 of the testing framework lists it.

## 13. Open questions

None.
