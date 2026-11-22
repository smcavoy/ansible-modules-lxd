# lxd_storage_volume_info

## 1. Purpose

Read storage volumes across all pools or in one pool, with optional usage.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/storage-volumes?recursion=1` | `GET` | Volumes in all pools. Needs `storage_volumes_all`. |
| `/1.0/storage-pools/{p}/volumes?recursion=1` | `GET` | Volumes in one pool. |
| `/1.0/storage-pools/{p}/volumes/{type}/{name}` | `GET` | One volume. |
| `/1.0/storage-pools/{p}/volumes/{type}/{name}/state` | `GET` | Usage. Needs `storage_volume_state`. |

Required API extensions: `storage`. With `filter`: `storage_volume_api_filtering`. With `all_projects`: `storage_volumes_all_projects`.

## 3. Identity

`pool`, `type`, `name`, and `project`, if set.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | no | One pool. Without it, all pools. |
| `name` | str | | no | One volume. Needs `pool`. A missing volume gives an empty list. |
| `type` | str | | no | `custom`, `container`, `virtual-machine`, or `image`. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Volumes in all projects. Mutually exclusive with `project`. |
| `filter` | str | | no | An LXD filter expression, for example `content_type eq block`. |
| `include_state` | bool | `false` | no | Add `state.usage` to each volume. |
| `target` | str | | no | The member for a volume on a local pool. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `storage_volumes` | list | Each item is a volume object with `pool`. With `include_state`, it has `state.usage`. |

```yaml
storage_volumes:
  - name: data
    type: custom
    pool: default
    content_type: filesystem
    config:
      size: 5GiB
    state:
      usage:
        used: 1048576
        total: 5368709120
```

## 9. Errors

| Case | Message |
|---|---|
| `name` without `pool`. | Ansible `required_by` error. |
| A bad `filter`. | The LXD error. |

## 10. Cluster behavior

Volumes on local pools have `location`. `target` selects the member for one volume.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| VI1 | `type: container` lists the root volume of a container. | The list holds the container name. |
| VI2 | `filter` with `content_type eq block` lists only block volumes. | Every item has `content_type: block`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
