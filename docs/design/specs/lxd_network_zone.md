# lxd_network_zone

## 1. Purpose

Create, update, and delete DNS zones that LXD serves for its networks.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/network-zones/{zone}` | `GET` | sync, `ETag` | Read. |
| `/1.0/network-zones` | `POST` | async | Create. |
| `/1.0/network-zones/{zone}` | `PUT` | sync or async, checks `If-Match` | Update. |
| `/1.0/network-zones/{zone}` | `DELETE` | async | Delete. |

Required API extensions: `network_dns`. With a project other than `default`: `projects_networks_zones`.

## 3. Identity

`name` and `project`. The name is a DNS name, for example `lxd.example.net`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The zone name. |
| `project` | str | | no | The project needs `features.networks.zones` for its own zones. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Keys: `dns.nameservers`, `network.nat`, `peers.<name>.address`, `peers.<name>.key`, `user.*`. |
| `config_mode` | str | `merge` | no | Rule R4. |

`peers.<name>.key` holds a TSIG secret. The module masks its value in the diff and in the result.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/network-zones` with `name`, `description`, and `config`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `config`, with `peers.*.key` masked as `********`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `zone` | dict | The zone from `GET`, after the change. `null` after a delete. |

```yaml
zone:
  name: lxd.example.net
  description: Forward zone
  config:
    dns.nameservers: ns1.example.net
    peers.ns1.address: 192.0.2.53
    peers.ns1.key: "********"
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| Delete a zone in use by a network. | The LXD error, which names the network. |
| A zone that exists in another project. | The LXD error `The network zone already exists` |

## 10. Cluster behavior

None. Zones are global in a cluster.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C12.

| ID | Goal | Pass when |
|---|---|---|
| Z1 | A bridge with `dns.zone.forward` serves the zone. | `dig` against `core.dns_address` returns the record of a running container. |
| Z2 | `peers.<name>.key` is masked. | The result and the diff hold `********`. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should the module mask `peers.*.key` in `config`, or return it as the server does? This spec masks it.
