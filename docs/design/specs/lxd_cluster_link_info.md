# lxd_cluster_link_info

## 1. Purpose

Read cluster links and the status of the members of the other cluster.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/cluster/links?recursion=1` | `GET` | All links. |
| `/1.0/cluster/links/{name}` | `GET` | One link. |
| `/1.0/cluster/links/{name}/state` | `GET` | Address and status of each remote member. |

Required API extensions: `cluster_links`.

## 3. Identity

`name`, if set. Without `name`, all links.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One link. A missing link gives an empty list. |
| `include_state` | bool | `false` | no | Add `state.cluster_link_members` to each link. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `links` | list | Each item is a link object, with `state` on request. |

```yaml
links:
  - name: dr-site
    type: bidirectional
    state:
      cluster_link_members:
        - server_name: dr-ab12-1
          address: 10.0.0.41:8443
          status: Active
```

## 9. Errors

| Case | Message |
|---|---|
| A link with no known member address. | The LXD error `No cluster link member addresses found` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/multicluster`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| CKI1 | `include_state` shows the remote member. | One member has a status. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Record the `status` values of remote members in the first test run.
