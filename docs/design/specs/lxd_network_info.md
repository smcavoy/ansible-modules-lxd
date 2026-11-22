# lxd_network_info

## 1. Purpose

Read LXD networks, with optional runtime state and DHCP leases.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/networks?recursion=1` | `GET` | All networks in the project. |
| `/1.0/networks/{name}` | `GET` | One network. |
| `/1.0/networks/{name}/state` | `GET` | Runtime state. Needs `network_state`. |
| `/1.0/networks/{name}/leases` | `GET` | DHCP leases of a managed `bridge` or `ovn` network. |

Required API extensions: `network`. With `include_state`: `network_state`. With `all_projects`: `networks_all_projects`.

## 3. Identity

`name` and `project`, if set. Without `name`, all networks.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One network. A missing network gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Networks in all projects. Mutually exclusive with `project`. |
| `managed_only` | bool | `true` | no | Leave out host interfaces that LXD does not manage. |
| `include_state` | bool | `false` | no | Add `state` to each network. |
| `include_leases` | bool | `false` | no | Add `leases` to each managed `bridge` or `ovn` network. |
| `target` | str | | no | Read the state or leases of one cluster member. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `networks` | list | Each item is a network object, with `state` and `leases` on request. |

```yaml
networks:
  - name: lxdbr0
    type: bridge
    managed: true
    config:
      ipv4.address: 10.99.0.1/24
    state:
      state: up
      mtu: 1500
      addresses:
        - family: inet
          address: 10.99.0.1
          netmask: "24"
          scope: global
    leases:
      - hostname: c1
        address: 10.99.0.12
        hwaddr: 00:16:3e:aa:bb:cc
        type: dynamic
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

`target` selects the member for `state` and `leases`. Without `target`, LXD answers for the member that gets the request.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| NI1 | `include_state` on a bridge gives `state.state: up`. | The value is `up`. |
| NI2 | `include_leases` lists a running container. | A lease with the container name exists. |
| NI3 | `managed_only: false` lists `eth0` of the sandbox. | The list holds an unmanaged network. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
