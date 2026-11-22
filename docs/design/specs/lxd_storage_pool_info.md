# lxd_storage_pool_info

## 1. Purpose

Read LXD storage pools, with optional space usage.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/storage-pools?recursion=1` | `GET` | All pools. |
| `/1.0/storage-pools/{name}` | `GET` | One pool. |
| `/1.0/storage-pools/{name}/resources` | `GET` | Space and inode usage. |

Required API extensions: `storage`. With `include_resources`: `resources`.

## 3. Identity

`name`, if set. Without `name`, all pools.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One pool. A missing pool gives an empty list. |
| `include_resources` | bool | `false` | no | Add `resources` to each pool. |
| `target` | str | | no | Read local keys and resources of one cluster member. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `storage_pools` | list | Each item is a pool object. With `include_resources`, it has `resources`. |

```yaml
storage_pools:
  - name: default
    driver: dir
    status: Created
    config:
      source: /var/snap/lxd/common/lxd/storage-pools/default
    resources:
      space:
        used: 1073741824
        total: 21474836480
      inodes:
        used: 1200
        total: 1310720
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

Without `target`, `GET` omits local keys. With `target`, the result holds the local keys of that member.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| SPI1 | `include_resources` gives a total size. | `resources.space.total` is more than 0. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
