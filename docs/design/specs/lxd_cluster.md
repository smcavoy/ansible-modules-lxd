# lxd_cluster

## 1. Purpose

Turn clustering on for the first member, join a server to a cluster, or remove a member.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/cluster` | `GET` | sync, `ETag` | Read `enabled`, `server_name`, and `member_config`. |
| `/1.0/cluster` | `PUT` | async, ignores `If-Match` | Enable, or join. |
| `/1.0/cluster/members/{name}` | `DELETE` | sync | Remove a member. `?force=1` removes an offline member. |

Required API extensions: `clustering`. A join with a token needs `clustering_join_token` and `explicit_trust_token`.

## 3. Identity

The server that the module connects to.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `state` | str | `enabled` | no | `enabled`, `joined`, or `absent`. |
| `server_name` | str | | yes for `enabled` and `joined` | The member name. It cannot start with `@` or be `none`. |
| `cluster_token` | str | | yes for `joined` | Secret. The join token from `lxd_cluster_join_token`. |
| `server_address` | str | | yes for `joined` | The address of this server, `<ip>:8443`. |
| `join_config` | list of dict | | no | For `joined`. Values for member-specific keys that the cluster needs. Each item has `entity`, `name`, `key`, and `value`. |
| `member` | str | | yes for `absent` | The member to remove. |
| `force` | bool | `false` | no | For `absent`. Remove a member that does not answer. |

The name `join_config` differs from `member_config` in other modules on purpose. Here it is a list in the API join format.

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `enabled`

| Case | Action |
|---|---|
| Not clustered | `PUT /1.0/cluster` with `server_name` and `enabled: true`. Wait for the operation. |
| Clustered with the same name | No request. `changed: false`. |
| Clustered with another name | Fail. The module does not rename members. |

LXD needs `cluster.https_address`, or a `core.https_address` that is not a wildcard. Set it with `lxd_server_config` first.

### `joined`

| Case | Action |
|---|---|
| Not clustered | `PUT /1.0/cluster` with `server_name`, `enabled: true`, `server_address`, `cluster_token`, and `member_config` from `join_config`. |
| Clustered | No request. `changed: false`. The module does not check that it is the same cluster. |

The module decodes the token to find the cluster addresses and fingerprint. It never prints the token.
The join request needs the PEM certificate of the cluster. The module reads it from the token addresses and joins only when its SHA-256 matches the token fingerprint. This answers open question 1.
A joined server presents the cluster certificate, which names the first member. The module checks the join on a connection that pins that certificate without a host name check.
The joining server must have no instances, pools, or networks that clash with the cluster.

### `absent`

| Case | Action |
|---|---|
| `member` is not in the cluster | No request. `changed: false`. |
| `member` is in the cluster | `DELETE /1.0/cluster/members/{member}`, with `?force=1` if `force` is true. |

## 7. Check and diff mode

The diff holds `enabled` and `server_name`. Check mode sends no request. For `joined`, it also does not read the certificate from the token addresses.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `cluster` | dict | `GET /1.0/cluster` after the change, without secrets. |
| `certificate` | str | For `enabled` and `joined`: the PEM certificate that the server presents after the task. Enabling makes a new cluster certificate. Later tasks need it as `server_cert`. |

```yaml
cluster:
  server_name: cls-ab12-1
  enabled: true
  member_config:
    - entity: storage-pool
      name: local
      key: source
      value: ""
      description: '"source" property for storage pool "local"'
```

## 9. Errors

| Case | Message |
|---|---|
| `enabled` with a wildcard address and no `cluster.https_address`. | The LXD error `Cannot use wildcard core.https_address ...` |
| `joined` on a server that is already clustered elsewhere. | The LXD error `This server is already clustered` |
| `joined` without `server_address`. | The LXD error `No server address provided for this member` |
| A bad token. | `cluster_token is not a valid join token` |
| A name that starts with `@`. | The LXD error `ServerName may not start with "@"` |

## 10. Cluster behavior

This module forms the cluster. Run `enabled` against member 1. Run `joined` against each new member.

## 11. Tests

Fixture: `lxd/cluster-new`, 3 fresh, unclustered VMs. See section 6 of the testing framework.

| ID | Goal | Pass when |
|---|---|---|
| CL1 | `enabled` on member 1. | `GET /1.0/cluster` shows `enabled: true`. |
| CL2 | A second `enabled` makes no change. | `changed` is false. |
| CL3 | `joined` on member 2 and 3 with tokens. | `lxd_cluster_member_info` lists 3 members `Online`. |
| CL4 | `absent` removes member 3. | 2 members remain. |
| CL5 | A second `absent` makes no change. | `changed` is false. |
| CL6 | Check mode on `joined` sends no request. | Member 3 stays standalone. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `joined` check the cluster fingerprint against the token, to detect a server in another cluster? The module checks the certificate of the token addresses before a join. It does not check a server that is clustered already.
