# lxd_network

## 1. Purpose

Create, update, and delete managed LXD networks of type `bridge`, `macvlan`, `sriov`, `ovn`, and `physical`.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/networks/{name}` | `GET` | sync, `ETag` | Read. With `?target=<member>`, read the local keys of one member. |
| `/1.0/networks` | `POST` | async | Create. With `?target=<member>`, create the pending member part. |
| `/1.0/networks/{name}` | `PUT` | async, checks `If-Match` | Update. With `?target=<member>`, update local keys. |
| `/1.0/networks/{name}` | `DELETE` | async | Delete. |

Required API extensions: `network`. With `project` other than `default`: `projects_networks`.
The OVN type needs `network_type_ovn`. The client also checks `clustering` before it uses `target`.

## 3. Identity

`name` and `project`. The module does not rename networks.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The network name. A bridge name has at most 15 characters. |
| `project` | str | | no | Only `ovn` networks can live in a project other than `default`. |
| `state` | str | `present` | no | `present` or `absent`. |
| `type` | str | `bridge` | no | Create-only. `bridge`, `macvlan`, `sriov`, `ovn`, or `physical`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `member_config` | dict | | no | Rule R6. Member name to local keys. |

## 5. Computed keys

`volatile.*`, `bridge.mtu`, `ipv4.address`, `ipv4.nat`, `ipv6.address`, `ipv6.nat`.

A task value `auto` for `ipv4.address` or `ipv6.address` equals any address on the server.
A task value `none` must match the server value `none`.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent, standalone | `POST /1.0/networks` with `name`, `type`, `description`, and `config`. |
| Absent, cluster | The pending-then-global flow from rule R6. |
| Present, `Pending` or `Errored` | Fail: `The network <name> has the status <status>: its cluster create did not finish ...`. The message names the members and says to remove the object with `state=absent` and run the task again. No write. The module does not complete the create. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` the global keys. Then `PUT ?target=<member>` for each member whose local keys differ. The body of that `PUT` is the config of the member view (global and local keys): LXD 6.10.1 replaces the whole config, and a body with only the local keys removes every global key. |
| `type` differs | Warn and continue. Rule R10. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `config`, and, on a cluster, `members`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `network` | dict | The network from `GET`, after the change. `null` after a delete. |
| `network.members` | dict | On a cluster: member name to local keys. |

```yaml
network:
  name: tb0ab121
  type: bridge
  managed: true
  status: Created
  description: Test bridge
  config:
    ipv4.address: 10.123.0.1/24
    ipv4.nat: "true"
    ipv6.address: none
  locations:
    - none
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| A non-OVN type in a project other than `default`. | The LXD error `Network type does not support non-default projects` |
| Delete a network in use. | The LXD error `The network is currently in use` |
| A global key in `member_config`. | `Config key <key> is not member specific` |
| Update while the network is `Pending` or `Errored`. | The LXD error `Cannot update network global config when not in created state` |
| Update an OVN network with `ipv6.address` on an uplink without IPv6. | The LXD error `Uplink address key "volatile.network.ipv6.address" cannot be empty ...`. LXD sets `ipv6.address` on create. Create the network with `ipv6.address: none`. |

## 10. Cluster behavior

Local keys: `bridge.external_interfaces`, `bgp.ipv4.nexthop`, `bgp.ipv6.nexthop` for `bridge`. `parent` for `macvlan`, `physical`, and `sriov`.
The module reads the scopes through `_cluster.py`. It never hard-codes this list.
A network that stays `Pending` or `Errored` after a failed create makes the task fail (section 6). `state=absent` removes it.
LXD 6.10.1: a create that stops after the member step stays `Pending`; a failed cluster step (for example a macvlan `parent` that does not exist) gives `Errored`.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_network` | `lxd/standalone` | C1 to C12 for a `bridge`. N1 to N4. |
| `lxd_network_cluster` | `lxd/cluster` | N5 to N7. |
| `lxd_network_ovn` | `lxd/ovn` | C1 to C12 for an `ovn` network in a test project. |

| ID | Goal | Pass when |
|---|---|---|
| N1 | `ipv4.address: auto` makes no change on the second run. | `changed` is false. |
| N2 | A `macvlan` network uses the second sandbox NIC as `parent`. | The network is `Created`. |
| N3 | A bridge in a test project fails. | `msg` holds `non-default projects`. |
| N4 | A change of `type` gives a warning. | `changed` is false. `warnings` names `type`. |
| N5 | A bridge with `member_config` per member reaches `Created`. | Each member shows its own `bgp.ipv4.nexthop`. |
| N6 | A change of one member key sends one targeted `PUT`. | Only that member changes. |
| N7 | A local key in `config` is the default for every member. | Each member shows the key with the `config` value. |

## 12. Hardware exceptions

`sriov` networks need an SR-IOV NIC. Unit tests cover the request body. The `physical` type uses the second sandbox NIC.

## 13. Open questions

None.
