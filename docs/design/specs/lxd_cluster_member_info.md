# lxd_cluster_member_info

## 1. Purpose

Read cluster members with their status, roles, and, on request, their system state.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/cluster/members?recursion=1` | `GET` | All members. |
| `/1.0/cluster/members/{name}` | `GET` | One member. |
| `/1.0/cluster/members/{name}/state` | `GET` | System info and pool usage. Needs `cluster_member_state`. |

Required API extensions: `clustering`.

## 3. Identity

`name`, if set. Without `name`, all members.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One member. A missing member gives an empty list. |
| `include_state` | bool | `false` | no | Add `state` to each member. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.
On a standalone server, it returns an empty list and `clustered: false`. It does not fail.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `clustered` | bool | Whether the server is clustered. |
| `members` | list | Each item is a member object. With `include_state`, it has `state.sysinfo` and `state.storage_pools`. |

```yaml
clustered: true
members:
  - server_name: cls-ab12-1
    status: Online
    roles:
      - database-leader
      - database
    state:
      sysinfo:
        uptime: 3600
        logical_cpus: 2
        total_ram: 3221225472
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

Run against any member.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_cluster_member_info` | `lxd/cluster` | I1 to I4. CMI1. |
| `lxd_cluster_member_info_standalone` | `lxd/standalone` | CMI2. |

| ID | Goal | Pass when |
|---|---|---|
| CMI1 | `include_state` shows RAM. | `state.sysinfo.total_ram` is more than 0. |
| CMI2 | A standalone server gives an empty list. | `clustered` is false. `members` is empty. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
