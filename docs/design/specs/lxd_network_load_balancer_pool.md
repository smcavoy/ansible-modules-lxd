# lxd_network_load_balancer_pool

## 1. Purpose

Create, update, and delete OVN load balancer pools of instances, with health checks.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/networks/{n}/load-balancer-pools/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/networks/{n}/load-balancer-pools` | `POST` | async | Create. |
| `/1.0/networks/{n}/load-balancer-pools/{name}` | `PUT` | async, ignores `If-Match` | Update. |
| `/1.0/networks/{n}/load-balancer-pools/{name}` | `DELETE` | async | Delete. |
| `/1.0/networks/{n}/load-balancer-pools/{name}/state` | `GET` | sync | Target status. |

Required API extensions: `network_load_balancer_pool`. Health check keys need `network_load_balancer_pool_health_checks`.

## 3. Identity

`network`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `network` | str | | yes | The OVN network. |
| `name` | str | | yes | The pool name. |
| `project` | str | | no | The project of the network and the instances. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. LXD requires `target_port` on create. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `instances` | list of dict | | no | Each item has `name` and an optional `target_port`. `null` means "do not manage". |

Config keys: `target_port` (required), `protocol` (default `tcp`), `healthcheck` (default `true`), `healthcheck.interval`, `healthcheck.timeout`, `healthcheck.success_count`, `healthcheck.failure_count`, `user.*`.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../load-balancer-pools` with `name`, `description`, `config`, and `instances`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. Rule R3 says that the server does not check `If-Match`. |

The module compares `instances` as a set by `name`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `config`, and `instances`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `load_balancer_pool` | dict | The pool from `GET`, after the change, with `state.targets`. `null` after a delete. |

```yaml
load_balancer_pool:
  name: web
  description: Web pool
  config:
    target_port: "80"
    healthcheck: "true"
  instances:
    - name: web1
      target_port: ""
  used_by: []
  state:
    targets:
      - name: web1
        address: 10.205.185.2
        port: "80"
        status: online
```

## 9. Errors

| Case | Message |
|---|---|
| Create without `config.target_port`. | `config.target_port is required on create` |
| The network is not OVN. | The LXD error `Network driver ... does not support load balancers` |
| A pool in use by a load balancer. | The LXD error on delete. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/ovn`. Standard cases C1 to C12.

| ID | Goal | Pass when |
|---|---|---|
| LP1 | A load balancer port with `target_pool` reaches pool members. | `curl` returns an answer. |
| LP2 | A stopped instance becomes `offline` in `state.targets`. | The status is not `online` after the health check interval. |
| LP3 | Instances in another order make no change. | `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. The values of `state.targets[].status` are not in the API docs. Record them in the first test run.

## 14. Findings from the tests

1. LXD adds `protocol: tcp` to the pool config.
2. An instance item has only `name` when the task gives no `target_port`.
3. The pool state is an empty object while the pool has no health check results.
4. A load balancer port with `target_pool` reaches the pool members.
