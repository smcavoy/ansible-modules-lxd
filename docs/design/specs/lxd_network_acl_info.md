# lxd_network_acl_info

## 1. Purpose

Read network ACLs and, on request, their log.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/network-acls?recursion=1` | `GET` | All ACLs in the project. |
| `/1.0/network-acls/{name}` | `GET` | One ACL. |
| `/1.0/network-acls/{name}/log` | `GET` | The ACL log as text. Only for OVN networks. Needs `network_acl_log`. |

Required API extensions: `network_acl`. With `all_projects`: `network_acls_all_projects`.

## 3. Identity

`name` and `project`, if set. Without `name`, all ACLs.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One ACL. A missing ACL gives an empty list. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | ACLs in all projects. Mutually exclusive with `project`. |
| `include_log` | bool | `false` | no | Add `log` to each ACL. Needs `name`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `acls` | list | Each item is an ACL object. With `include_log`, the item has `log` as a list of lines. |

```yaml
acls:
  - name: web-in
    ingress: []
    egress: []
    used_by:
      - /1.0/networks/ovn1
    log:
      - "2026-11-03T10:00:00Z ... action=allow ..."
```

## 9. Errors

| Case | Message |
|---|---|
| `include_log` without `name`. | `include_log needs name` |

## 10. Cluster behavior

None.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_network_acl_info` | `lxd/standalone` | I1 to I4. |
| `lxd_network_acl_info_log` | `lxd/ovn` | AI1. |

| ID | Goal | Pass when |
|---|---|---|
| AI1 | A logged rule on an OVN network writes a log line. | `log` holds at least one line after a ping. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
