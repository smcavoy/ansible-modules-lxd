# lxd_network_allocation_info

## 1. Purpose

Read the IP addresses that LXD networks, instances, forwards, and load balancers use.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/network-allocations` | `GET` | Allocations in one project, or with `?all-projects=true` in all projects. |

Required API extensions: `network_allocations`.

## 3. Identity

`project`, or all projects.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Allocations in all projects. Mutually exclusive with `project`. |
| `network` | str | | no | Keep only allocations on this network. The module filters on the client. |
| `type` | str | | no | Keep only this type: `network`, `uplink`, `instance`, `network-forward`, or `network-load-balancer`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `allocations` | list | Each item has `addresses`, `used_by`, `type`, `nat`, `hwaddr`, and `network`. |

```yaml
allocations:
  - addresses: 10.99.0.12/32
    used_by: /1.0/instances/c1
    type: instance
    nat: false
    hwaddr: 00:16:3e:aa:bb:cc
    network: lxdbr0
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. I1, I3, and I4. Skip I2, because allocations have no name.

| ID | Goal | Pass when |
|---|---|---|
| AL1 | A running container shows an allocation. | An item has `used_by` for the container. |
| AL2 | `network` filters the list. | Every item has that network. |
| AL3 | A missing network gives an empty list. | The list is empty. `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
