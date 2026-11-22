# lxd_server_info

## 1. Purpose

Read server facts: version, API extensions, environment, hardware resources, state, and config key metadata.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0` | `GET` | Server info, config, `api_extensions`, and `environment`. |
| `/1.0/resources` | `GET` | CPU, memory, GPU, network, storage, and PCI hardware. |
| `/1.0/state` | `GET` | Server state. Needs `server_state`. |
| `/1.0/metadata/configuration` | `GET` | Config key metadata. Needs `metadata_configuration`. |

Required API extensions: only those of the parts in `gather`.

## 3. Identity

Not applicable.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `gather` | list | `[server]` | no | Any of `server`, `resources`, `state`, `metadata`. |
| `target` | str | | no | Read `resources` and `state` of one cluster member. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change. Secret config values are masked, as in `lxd_server_config`.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `server` | dict | The `GET /1.0` metadata. |
| `resources` | dict | The `GET /1.0/resources` metadata. |
| `state` | dict | The `GET /1.0/state` metadata. |
| `metadata` | dict | The `GET /1.0/metadata/configuration` metadata. |

```yaml
server:
  api_version: "1.0"
  auth: trusted
  api_extensions:
    - storage_zfs_remove_snapshots
  environment:
    server_version: 6.10.1
    server_clustered: false
    server_name: sbx-ab12-1
    storage_supported_drivers:
      - name: dir
        remote: false
resources:
  cpu:
    total: 2
  memory:
    total: 3221225472
```

## 9. Errors

| Case | Message |
|---|---|
| A part needs a missing extension. | The shared extension error. |

## 10. Cluster behavior

`target` selects the member for `resources` and `state`.

## 11. Tests

Fixture: `lxd/standalone`. It runs SI1 to SI4 and I4. Skip I1 to I3, because the module has no `name` and returns no list.

| ID | Goal | Pass when |
|---|---|---|
| SI1 | `server` shows version 6.10.1 or newer. | `environment.server_version` parses as 6.10.1 or more. |
| SI2 | `resources` shows the vCPU count of the sandbox. | `cpu.total` is 2. |
| SI3 | `metadata` holds `scope` for `core.https_address`. | The scope is `local`. |
| SI4 | `state` returns without error. | `state` is a dictionary. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
