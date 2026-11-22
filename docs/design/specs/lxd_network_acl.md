# lxd_network_acl

## 1. Purpose

Create, update, and delete network ACLs with their ingress and egress rules.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/network-acls/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/network-acls` | `POST` | async | Create. |
| `/1.0/network-acls/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/network-acls/{name}` | `DELETE` | sync or async | Delete. |

Required API extensions: `network_acl`.

## 3. Identity

`name` and `project`. The module does not rename ACLs.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The ACL name. |
| `project` | str | | no | The project. It needs `features.networks` for its own ACLs. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `ingress` | list of dict | | no | Rules for incoming traffic. `null` means "do not manage". `[]` means no rules. |
| `egress` | list of dict | | no | Rules for outgoing traffic. Same rules as `ingress`. |
| `config` | dict | | no | Rule R4. Only `user.*` keys. |
| `config_mode` | str | `merge` | no | Rule R4. |

Rule fields:

| Field | Type | Default | Rule |
|---|---|---|---|
| `action` | str | | Required. `allow`, `reject`, or `drop`. |
| `state` | str | `enabled` | `enabled`, `disabled`, or `logged`. |
| `source`, `destination` | str | `""` | Comma-separated addresses, ranges, ACL names, or subjects. |
| `protocol` | str | `""` | `icmp4`, `icmp6`, `tcp`, `udp`, or `""` for any. |
| `source_port`, `destination_port` | str | `""` | Only with `tcp` or `udp`. |
| `icmp_type`, `icmp_code` | str | `""` | Only with `icmp4` or `icmp6`. |
| `description` | str | `""` | Free text. |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/network-acls` with all fields. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

The module fills each rule with the defaults above, then compares the rule lists as sets.
Rule order does not change the result in LXD. A change sends the rules in task order.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `ingress`, `egress`, and `config`. Each rule list is sorted for a stable diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `acl` | dict | The ACL from `GET`, after the change. `null` after a delete. |

```yaml
acl:
  name: web-in
  description: Allow HTTP in
  ingress:
    - action: allow
      state: enabled
      protocol: tcp
      destination_port: "80,443"
      source: ""
      destination: ""
      source_port: ""
      icmp_type: ""
      icmp_code: ""
      description: ""
  egress: []
  config: {}
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| A rule without `action`. | `rule <n> in ingress needs an action` |
| A port with a protocol other than `tcp` or `udp`. | The LXD validation error. |
| Delete an ACL in use. | The LXD error, which names the user. |

## 10. Cluster behavior

None. ACLs are global in a cluster.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C12. C6 to C8 use `user.*` keys.

| ID | Goal | Pass when |
|---|---|---|
| A1 | The same rules in another order make no change. | `changed` is false. |
| A2 | A rule without `state` equals a rule with `state: enabled`. | `changed` is false. |
| A3 | `ingress: []` removes all ingress rules. | The server has no ingress rules. |
| A4 | A bridge NIC with the ACL blocks a port. | A `curl` from another container to that port fails. |

## 12. Hardware exceptions

None. ACLs work on bridge networks in the sandbox.

## 13. Open questions

1. Should the module keep rule order for a later LXD that uses order? This spec compares as sets.

## 14. Findings from the tests

1. A `PATCH` on an ACL merges only the config. It replaces `description`, `ingress`, and `egress` with the request values.
   A missing field becomes empty. So the module uses `PUT` with the full object, and a test `PATCH` sends all fields.
