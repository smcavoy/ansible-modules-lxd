# lxd_network_load_balancer

## 1. Purpose

Create, update, and delete OVN load balancers with their backends and ports.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/networks/{n}/load-balancers/{address}` | `GET` | sync, `ETag` | Read. |
| `/1.0/networks/{n}/load-balancers` | `POST` | sync or async | Create. |
| `/1.0/networks/{n}/load-balancers/{address}` | `PUT` | sync or async, ignores `If-Match` | Update. |
| `/1.0/networks/{n}/load-balancers/{address}` | `DELETE` | sync or async | Delete. |

Required API extensions: `network_load_balancer`. A port with `target_pool` needs `network_load_balancer_pool`.
Only `ovn` networks support load balancers.

## 3. Identity

`network`, `listen_address`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `network` | str | | yes | The OVN network. |
| `listen_address` | str | | yes | The external IP address. |
| `project` | str | | no | The project of the network. It needs `features.networks`. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `backends` | list of dict | | no | Each item has `name`, `target_address`, `target_port`, and `description`. `null` means "do not manage". |
| `ports` | list of dict | | no | Each item has `protocol`, `listen_port`, `target_backend`, `target_pool`, and `description`. `null` means "do not manage". |

`target_backend` is a list of backend names. A port uses `target_backend` or `target_pool`, not both.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../load-balancers` with all fields. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. Rule R3 says that the server does not check `If-Match`. |

The module compares `backends` as a set by `name`, and `ports` as a set.
A missing backend `target_port` equals the port `listen_port`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `config`, `backends`, and `ports`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `load_balancer` | dict | The load balancer from `GET`, after the change. `null` after a delete. |

```yaml
load_balancer:
  listen_address: 192.0.2.150
  description: Web pool
  config: {}
  backends:
    - name: web1
      target_address: 10.205.185.2
      target_port: "80"
      description: ""
  ports:
    - protocol: tcp
      listen_port: "80"
      target_backend:
        - web1
      target_pool: ""
      description: ""
```

## 9. Errors

| Case | Message |
|---|---|
| The network is not OVN. | The LXD error `Network driver ... does not support load balancers` |
| A port with both `target_backend` and `target_pool`. | `port <n> takes target_backend or target_pool, not both` |
| A port names a missing backend. | `port <n> names an unknown backend <name>` |
| A project without `features.networks`. | The LXD error `Project ... requires features.networks=true` |

## 10. Cluster behavior

None. OVN load balancers are global.

## 11. Tests

Fixture: `lxd/ovn`. Standard cases C1 to C12.

| ID | Goal | Pass when |
|---|---|---|
| LB1 | Traffic reaches both backends. | Two `curl` calls return answers from two containers. |
| LB2 | Backends in another order make no change. | `changed` is false. |
| LB3 | A port that names an unknown backend fails early. | `msg` holds `unknown backend`. No request is sent. |

## 12. Hardware exceptions

None. The `lxd/ovn` fixture uses MicroOVN.

## 13. Open questions

None.

## 14. Findings from the tests

1. The listen address must be in the `ipv4.routes` of the uplink network. The test adds a route range to `UPLINK` and removes it after the test.
2. A client on the same OVN network reaches the listen address. Both backends answer.
3. The backends in the test serve with a `nc` loop. About 3 of 10 requests get no answer, because the loop restarts after each connection.
