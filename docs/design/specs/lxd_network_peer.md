# lxd_network_peer

## 1. Purpose

Create, update, and delete peer connections between two OVN networks.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/networks/{n}/peers/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/networks/{n}/peers` | `POST` | async | Create. |
| `/1.0/networks/{n}/peers/{name}` | `PUT` | async, ignores `If-Match` | Update. |
| `/1.0/networks/{n}/peers/{name}` | `DELETE` | async | Delete. |

Required API extensions: `network_peer`. Only `ovn` networks support peers.

## 3. Identity

`network`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `network` | str | | yes | The local OVN network. |
| `name` | str | | yes | The peer name. |
| `project` | str | | no | The project of the local network. |
| `target_project` | str | | no | Create-only. The project of the other network. Default: `project`. |
| `target_network` | str | | yes for create | Create-only. The other OVN network. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Only `user.*` keys. |
| `config_mode` | str | `merge` | no | Rule R4. |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../peers` with `name`, `target_project`, `target_network`, `description`, and `config`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `description` and `config`. |
| `target_network` or `target_project` differs | Warn and continue. Rule R10. |

A peer stays `Pending` until the other network has a peer back to this network. Then both become `Created`.
The module does not wait for `Created`. It returns `status`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `peer` | dict | The peer from `GET`, after the change. `null` after a delete. |

```yaml
peer:
  name: to-ovn2
  description: ""
  target_project: default
  target_network: ovn2
  status: Created
  config: {}
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| The network is not OVN. | The LXD error `Network driver ... does not support peering` |
| A second peer to the same network. | The LXD error `A peer for that target network already exists` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/ovn`. Standard cases C1 to C12. C6 to C8 use `user.*` keys.

| ID | Goal | Pass when |
|---|---|---|
| PE1 | One side gives `Pending`. | `status` is `Pending`. |
| PE2 | Both sides give `Created`. | Both peers show `Created`. A container on one network pings a container on the other. |
| PE3 | A change of `target_network` gives a warning. | `changed` is false. `warnings` names `target_network`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.

## 14. Findings from the tests

1. A one-way peer is `Pending`. When the peer back exists, both are `Created`.
2. When one side of a mutual peer is deleted, the other side becomes `Errored`.
3. The tests run on the MicroCloud fixture, with OVN networks on its `UPLINK`.
