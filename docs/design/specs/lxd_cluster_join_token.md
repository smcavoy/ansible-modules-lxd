# lxd_cluster_join_token

## 1. Purpose

Issue a join token for a new cluster member name, or revoke open tokens.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/cluster/members` | `POST` | async | Issue a token for `server_name`. The operation metadata holds the token data. |
| `/1.0/operations?recursion=1` | `GET` | sync | Find open join tokens. |
| `/1.0/operations/{id}` | `DELETE` | sync | Revoke a token. |

Required API extensions: `clustering_join_token`. With expiry: `cluster_join_token_expiry`.

## 3. Identity

`name`, the new member name. An open token is a running operation of class `token` with that `serverName`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The new member name. |
| `state` | str | `present` | no | `present` issues a token. `absent` revokes open tokens for `name`. |
| `force` | bool | `false` | no | Issue a new token even if one is open. |

The token lifetime comes from the server key `cluster.join_token_expiry`.

## 5. Computed keys

Not applicable.

## 6. Behavior per state

This is an action module for `present`. Rule R8.

| State | Case | Action |
|---|---|---|
| `present` | `name` is already a member | No request. `changed: false`. |
| `present` | No open token, or `force` | `POST /1.0/cluster/members` with `server_name`. Build the token from the operation metadata. |
| `present` | An open token exists | No request. `changed: false`. No token in the result. |
| `absent` | Open tokens exist | `DELETE` each operation. |
| `absent` | No open token | No request. `changed: false`. |

The token is the base64 encoding of a JSON object with `server_name`, `fingerprint`, `addresses`, `secret`, and `expires_at`.

## 7. Check and diff mode

Check mode sends no request. It reports the predicted change. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `token` | str | The join token. Only when the module issues one. Secret. Rule R9. |
| `expires_at` | str | The expiry. |
| `operation` | str | The operation ID. |

```yaml
token: eyJzZXJ2ZXJfbmFtZSI6ImNscy1hYjEyLTIi...
expires_at: "2026-11-03T13:00:00Z"
operation: 01a1a00a-6ae7-7412-8972-aea8529f209b
```

## 9. Errors

| Case | Message |
|---|---|
| The server is not clustered. | The LXD error `This server is not clustered` |
| A reserved name. | The LXD error `Join token name cannot be ...` |

## 10. Cluster behavior

Run against any member of the cluster.

## 11. Tests

Fixture: `lxd/cluster`. It runs JT1 to JT4. `lxd_cluster` tests use this module for joins.

| ID | Goal | Pass when |
|---|---|---|
| JT1 | A token for a new name. | `token` is set. |
| JT2 | A second run does not issue a new token. | `changed` is false. |
| JT3 | `absent` revokes the token. | A join with it fails. |
| JT4 | A token for an existing member makes no change. | `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
