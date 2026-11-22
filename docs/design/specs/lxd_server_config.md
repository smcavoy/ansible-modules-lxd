# lxd_server_config

## 1. Purpose

Manage the server config keys of a standalone LXD server or a cluster, including member keys.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0` | `GET` | sync, `ETag` | Read `config`. With `?target=<member>`, read the local keys of one member. |
| `/1.0` | `PUT` | sync, checks `If-Match` | Write the full `config`. With `?target=<member>`, write local keys. |

Required API extensions: none beyond the base API. `member_config` needs `clustering`.

## 3. Identity

Not applicable. There is one server config.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `config` | dict | | no | Rule R4. Global and local keys. |
| `config_mode` | str | `merge` | no | Rule R4. Use `exact` with care. It removes keys that other tools set. |
| `member_config` | dict | | no | Rule R6. Member name to local keys. |

Local keys include `core.https_address`, `cluster.https_address`, `core.bgp_address`, `core.bgp_routerid`, `core.debug_address`, `core.dns_address`, `core.metrics_address`, `core.syslog_socket`, `storage.backups_volume`, `storage.images_volume`, and the `storage.project.*` volume keys.

## 5. Computed keys

`volatile.uuid`. The module also never removes `cluster.https_address` and `core.https_address` with `exact`.
A removal of these keys can cut the connection of the task itself.

## 6. Behavior per state

The module has no `state`.

| Case | Action |
|---|---|
| Same | No request. `changed: false`. |
| Global keys differ | `PUT /1.0` with the full global config. A removed key goes in with an empty value. |
| Local keys differ, standalone | The same `PUT /1.0`. A standalone server has no split. |
| Local keys differ, cluster | `PUT /1.0?target=<member>` for each member that differs. |

Secret keys are `loki.auth.password`, `oidc.client.secret`, and `network.ovn.client_key`.
The module masks their values in the diff and the result. It compares them by value, because LXD returns them.

A change of `core.https_address` on the address that the task uses can end the connection.
The module warns about this before it sends the request.

## 7. Check and diff mode

The diff holds the changed keys, with secret values masked. On a cluster, it also holds `members`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `config` | dict | The global config after the change, with secret values masked. |
| `members` | dict | On a cluster: member name to local keys. |

```yaml
config:
  core.https_address: "[::]:8443"
  images.auto_update_interval: "6"
  oidc.client.secret: "********"
members:
  cls-ab12-1:
    core.https_address: 10.0.0.31:8443
```

## 9. Errors

| Case | Message |
|---|---|
| A value that is not a string after conversion. | The LXD error `Invalid config value type for ...: expected string` |
| An unknown key. | The LXD validation error. |
| `member_config` on a standalone server. | `member_config is only valid on a clustered server` |

## 10. Cluster behavior

Rule R6. `GET /1.0` without `target` gives the global keys and the local keys of the member that answers.
The module reads each member with `?target=` to compare local keys.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_server_config` | `lxd/standalone` | C4 to C9 with `user.*` and `images.*` keys. SC1 to SC3. |
| `lxd_server_config_cluster` | `lxd/cluster` | SC4 and SC5. |

Skip C1 to C3 and C10 to C12, because the server config always exists.

| ID | Goal | Pass when |
|---|---|---|
| SC1 | `exact` keeps `core.https_address`. | The key stays. The sandbox still answers. |
| SC2 | A secret key is masked. | The result shows `********` for `oidc.client.secret`. |
| SC3 | A number value becomes a string. | `images.auto_update_interval: 12` makes no change on the second run. |
| SC4 | `member_config` sets `core.metrics_address` on one member. | Only that member has the key. |
| SC5 | A second run on the cluster makes no change. | `changed` is false. |

## 12. Hardware exceptions

ACME keys need public DNS and port 80. Test them as config only. See section 13 of the testing framework.

## 13. Open questions

1. Should the module refuse a change of `core.https_address` on the address in use, instead of a warning? This spec warns.

## 14. Findings from the tests

1. A `PUT /1.0` changes only the keys in the body. LXD keeps the keys that the body leaves out.
   To remove a key, the module sends it with an empty value.
2. On a cluster, `PUT /1.0?target=<member>` applies the full body to the cluster-wide keys too.
   So each member body holds the new global keys and the member keys.
3. LXD does not store a key at its default value. The default of `images.auto_update_interval` is `6`.
   A task that sets a key to its default reports a change on every run. SC3 uses `12` for this reason.
4. LXD can reset the connection right after a config change. The client sends a `GET` once more after a connection error.
