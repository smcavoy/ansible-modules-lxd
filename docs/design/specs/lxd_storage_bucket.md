# lxd_storage_bucket

## 1. Purpose

Create, update, and delete S3 object storage buckets on a `cephobject` pool.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{p}/buckets/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/storage-pools/{p}/buckets` | `POST` | async | Create. The operation returns the initial admin credentials. |
| `/1.0/storage-pools/{p}/buckets/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/storage-pools/{p}/buckets/{name}` | `DELETE` | async | Delete. |

Required API extensions: `storage_buckets`. Initial credentials need `storage_buckets_create_credentials`.
LXD 6.8 removed local buckets. Only `cephobject` pools hold buckets.

## 3. Identity

`pool`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | yes | A `cephobject` pool. |
| `name` | str | | yes | The bucket name. It follows S3 naming rules. |
| `project` | str | | no | The project. It needs `features.storage.buckets` for its own buckets. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Keys: `size` and `user.*`. |
| `config_mode` | str | `merge` | no | Rule R4. |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../buckets` with `name`, `description`, and `config`. LXD also creates a key named `admin`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. LXD deletes the bucket keys too. |

## 7. Check and diff mode

The diff holds `description` and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `bucket` | dict | The bucket from `GET`, with `s3_url`. `null` after a delete. |
| `admin_credentials` | dict | Only on the run that creates the bucket. Keys `access_key` and `secret_key`. Secret. Rule R9. |

The create operation metadata holds a `key` object with the API fields `access-key` and `secret-key`.
The module renames them to `access_key` and `secret_key`. It does not pass the raw object on.

```yaml
bucket:
  name: backups
  description: ""
  s3_url: https://192.0.2.20:8080/backups
  config:
    size: 10GiB
admin_credentials:
  access_key: AKIAEXAMPLE
  secret_key: "********"
```

## 9. Errors

| Case | Message |
|---|---|
| The pool driver does not support buckets. | The LXD error `Storage pool driver ... does not support buckets` |
| A bucket name that breaks S3 rules. | The LXD validation error. |

## 10. Cluster behavior

None. `cephobject` buckets are global.

## 11. Tests

Fixture: `lxd/ceph`. Standard cases C1 to C12.

| ID | Goal | Pass when |
|---|---|---|
| B1 | The create returns admin credentials once. | `admin_credentials.access_key` is set on create and absent on the second run. |
| B2 | The admin key can write an object. | An S3 `PUT` with the credentials gives HTTP `200`. |

The `ceph` fixture needs a RADOS gateway for `cephobject`. Add `microceph enable rgw` to the fixture.

## 12. Hardware exceptions

None, after the fixture adds the RADOS gateway.

## 13. Open questions

1. The first tests did not cover `cephobject`. Check that `microceph enable rgw` works in the sandbox before the module is written.

## 14. Findings from the tests

1. A `cephobject` pool needs `cephobject.radosgw.endpoint`. The MicroCloud fixture enables the RADOS gateway on its first member.
2. The create operation returns the admin credentials. The module returns them only on that run.
3. A GET returns the internal fields `ID`, `PoolID`, and `PoolName`, and `volatile.uuid` in the config.
4. The runner has no S3 client. The target sends B2 and BK1 with `files/s3_request.py`, a small client with AWS signature version 4 that takes its keys from the environment.
