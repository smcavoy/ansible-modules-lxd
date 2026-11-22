# lxd_network_forward

## 1. Purpose

Create, update, and delete network forwards that send traffic from a listen address to instances.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/networks/{n}/forwards/{address}` | `GET` | sync, `ETag` | Read. |
| `/1.0/networks/{n}/forwards` | `POST` | sync or async | Create. |
| `/1.0/networks/{n}/forwards/{address}` | `PUT` | sync or async, ignores `If-Match` | Update. |
| `/1.0/networks/{n}/forwards/{address}` | `DELETE` | sync or async | Delete. |

Required API extensions: `network_forward`.
Only `bridge` and `ovn` networks support forwards.

## 3. Identity

`network`, `listen_address`, `project`, and, for a bridge on a cluster, `target`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `network` | str | | yes | The parent network. |
| `listen_address` | str | | yes | The external IP address. |
| `project` | str | | no | The project of the network. |
| `target` | str | | no | For a `bridge` on a cluster: the member that owns the forward. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Keys: `target_address` for the default target, and `user.*`. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `ports` | list of dict | | no | Port rules. `null` means "do not manage". `[]` means no port rules. |

Port fields: `protocol` (`tcp` or `udp`, required), `listen_port` (required), `target_address` (required), `target_port`, and `description`.
`listen_port` and `target_port` take a port, a range, or a comma-separated list.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../forwards` with `listen_address`, `description`, `config`, and `ports`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. Rule R3 says that the server does not check `If-Match`. |

The module compares `ports` as a set. A missing `target_port` equals `listen_port`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `config`, and `ports`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `forward` | dict | The forward from `GET`, after the change. `null` after a delete. |

```yaml
forward:
  listen_address: 192.0.2.100
  location: ""
  description: Web
  config:
    target_address: 10.99.0.20
  ports:
    - protocol: tcp
      listen_port: "443"
      target_address: 10.99.0.21
      target_port: "8443"
      description: ""
```

## 9. Errors

| Case | Message |
|---|---|
| The network type does not support forwards. | The LXD error `Network driver ... does not support forwards` |
| A target address outside the network subnet. | The LXD error `Target address is not within the network subnet ...` |
| A port rule without `listen_port`. | The LXD error `Missing listen port in port specification <n>` |

## 10. Cluster behavior

For a `bridge` on a cluster, a forward belongs to one member. Rule R6 applies to `target`.
For an `ovn` network, forwards are global. `target` fails with `target is not valid for ovn forwards`.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_network_forward` | `lxd/standalone` | C1 to C12 on a bridge. F1 to F3. |
| `lxd_network_forward_ovn` | `lxd/ovn` | C1 to C5, C10 to C12 on an OVN network. The bridge target covers C6 to C9, because the config code does not depend on the network type. |

| ID | Goal | Pass when |
|---|---|---|
| F1 | Ports in another order make no change. | `changed` is false. |
| F2 | A port without `target_port` equals one with the same port. | `changed` is false. |
| F3 | Traffic reaches the target. | `curl` to the listen address and port returns the test page. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. LXD can pick an OVN listen address with `network_allocate_external_ips`. Should the module support that? It breaks identity by `listen_address`. This spec does not support it.

## 14. Findings from the tests

1. A `PATCH` on a forward without `description` sets the description to empty. The module uses `PUT` with the full object.
