# lxd_storage_bucket_key

## 1. Purpose

Create, update, and delete access keys for a storage bucket.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{p}/buckets/{b}/keys/{name}` | `GET` | sync, `ETag` | Read. The result holds the secret. |
| `/1.0/storage-pools/{p}/buckets/{b}/keys` | `POST` | async | Create. |
| `/1.0/storage-pools/{p}/buckets/{b}/keys/{name}` | `PUT` | async, ignores `If-Match` | Update. |
| `/1.0/storage-pools/{p}/buckets/{b}/keys/{name}` | `DELETE` | async | Delete. |

Required API extensions: `storage_buckets`.

## 3. Identity

`pool`, `bucket`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | yes | The `cephobject` pool. |
| `bucket` | str | | yes | The bucket. |
| `name` | str | | yes | The key name. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `role` | str | `read-only` | no | `admin` or `read-only`. |
| `access_key` | str | | no | Set a fixed access key. Without it, LXD makes one on create. |
| `secret_key` | str | | no | Secret. Set a fixed secret key. Without it, LXD makes one on create. |

## 5. Computed keys

`access_key` and `secret_key` are computed when the task does not set them.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../keys` with `name`, `description`, `role`, and the keys if set. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. Rule R3 says that the server does not check `If-Match`. |

The module compares `secret_key` only when the task sets it. It never shows the value in the diff.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `role`, and `access_key`. A change of `secret_key` shows as `secret_key: changed`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `key` | dict | The key from `GET`, with `secret_key` masked. `null` after a delete. |
| `secret_key` | str | Only on the run that creates the key, or that changes `secret_key`. Secret. Rule R9. |

```yaml
key:
  name: reader
  description: ""
  role: read-only
  access_key: AKIAEXAMPLE2
  secret_key: "********"
secret_key: wJalrEXAMPLEKEY
```

## 9. Errors

| Case | Message |
|---|---|
| The bucket does not exist. | `bucket <bucket> not found in pool <pool>` |
| A bad `role`. | Ansible `choices` error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/ceph`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because keys have no config.

| ID | Goal | Pass when |
|---|---|---|
| BK1 | A `read-only` key cannot write. | An S3 `PUT` with the key fails with HTTP `403`. |
| BK2 | The secret is in the result only on create. | `secret_key` is absent on the second run. |
| BK3 | A fixed `secret_key` makes no change on the second run. | `changed` is false. |

## 12. Hardware exceptions

None, after the `ceph` fixture adds the RADOS gateway.

## 13. Open questions

1. The `admin` key comes from the bucket create. Should this module refuse to manage it? This spec allows it.

## 14. Findings from the tests

1. The API uses the field names `access-key` and `secret-key` with dashes.
2. A fixed `secret_key` makes no change on the second run.
