# lxd_storage_volume

## 1. Purpose

Create, update, copy, import, and delete custom storage volumes.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{p}/volumes/custom/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/storage-pools/{p}/volumes/custom` | `POST` JSON | async | Create empty, or copy. |
| `/1.0/storage-pools/{p}/volumes/custom` | `POST` binary | async | Import an ISO, a tarball, or a backup file. |
| `/1.0/storage-pools/{p}/volumes/custom/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/storage-pools/{p}/volumes/custom/{name}` | `DELETE` | async | Delete. |

Required API extensions: `storage_api_local_volume_handling`. `content_type: block` needs `custom_block_volumes`.
ISO import needs `custom_volume_iso`. Tarball import needs `import_custom_volume_tar`. Backup import needs `custom_volume_backup`.

## 3. Identity

`pool`, `name`, `project`, and, for a local pool on a cluster, `target`. The module manages only volumes of type `custom`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | yes | The storage pool. |
| `name` | str | | yes | The volume name. |
| `project` | str | | no | The project. It needs `features.storage.volumes` for its own volumes. |
| `target` | str | | no | The member for a volume on a local pool. Rule R6. |
| `state` | str | `present` | no | `present` or `absent`. |
| `content_type` | str | `filesystem` | no | Create-only. `filesystem`, `block`, or `iso`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. For example `size`, `block.filesystem`, `security.shifted`. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `source` | dict | | no | Create-only. See the source table below. |

Source keys. Each `source` holds exactly one of these forms:

| Form | Keys | Request |
|---|---|---|
| Copy | `volume`, optional `pool`, `project`, `snapshot`, `volume_only`, `refresh` | JSON `POST` with `source.type: copy`. A snapshot source uses the name `<volume>/<snapshot>`. |
| ISO | `iso_path` on the controller | Binary `POST` with `X-LXD-name` and `X-LXD-type: iso`. |
| Tarball | `tarball_path` on the controller | Binary `POST` with `X-LXD-name` and `X-LXD-type: tar`. |
| Backup | `backup_path` on the controller | Binary `POST` with `X-LXD-name`. |

The module streams the file from the controller. It does not read the whole file into memory.

## 5. Computed keys

`volatile.*`, `block.filesystem`, `block.mount_options`.
A key is also computed when the pool has `volume.<key>` and the task does not set `<key>`. For example, pool `volume.size` fills `size`.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent, no `source` | JSON `POST` with `name`, `type: custom`, `content_type`, `description`, and `config`. |
| Absent, with `source` | The request for the source form. Then `PUT` `description` and `config` if they differ from the result. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |
| `content_type` differs | Warn and continue. Rule R10. |
| `source` set on an existing volume | Ignore it and warn that `source` applies only on create. Exception: a copy with `refresh: true` sends the copy again. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `config`. On create, `after` also holds `source` without file paths.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `storage_volume` | dict | The volume from `GET`, after the change. `null` after a delete. |

```yaml
storage_volume:
  name: data
  type: custom
  pool: default
  project: default
  content_type: filesystem
  location: none
  description: ""
  config:
    size: 5GiB
  created_at: "2026-11-03T10:00:00Z"
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| Delete a volume in use. | The LXD error `The storage volume is still in use` |
| A source file does not exist. | `source file <path> not found` |
| More than one source form. | Ansible `mutually_exclusive` error. |
| A smaller `size` on a filesystem volume. | The LXD error. |

## 10. Cluster behavior

On a local pool, such as `dir` or `zfs`, a volume lives on one member. Set `target` on create.
On a remote pool, such as `ceph`, `target` is not needed.
Without `target` on a local pool, LXD picks the member that gets the request. The module warns in that case.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_storage_volume` | `lxd/standalone` | C1 to C12. V1 to V5. |
| `lxd_storage_volume_cluster` | `lxd/cluster` | V6. |

| ID | Goal | Pass when |
|---|---|---|
| V1 | A `block` volume reports `content_type: block`. | The value is `block`. |
| V2 | A copy of a volume holds the same file. | An instance with the copy reads the file. |
| V3 | A copy from a snapshot holds the old file. | The copy has the file from the snapshot time. |
| V4 | An ISO import gives `content_type: iso`. | The value is `iso`. |
| V5 | A pool `volume.size` does not cause a change. | `changed` is false on the second run. |
| V6 | `target` places the volume on member 2. | `location` is member 2. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should a backup import be a source here, or a separate module? This spec makes it a source.

## 14. Findings from the tests

1. A `PATCH` on a custom volume without `description` sets the description to empty. The module uses `PUT` with the full object.
