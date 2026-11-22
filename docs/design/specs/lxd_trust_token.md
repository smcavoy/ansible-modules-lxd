# lxd_trust_token

## 1. Purpose

Issue a trust token that lets a new client add its own certificate to the trust store.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/certificates` | `POST` | async | Issue a token, with `token: true`. The operation metadata holds the token data. |
| `/1.0/operations?recursion=1` | `GET` | sync | Find an open token for the same `name`. |
| `/1.0/operations/{id}` | `DELETE` | sync | Revoke a token. |

Required API extensions: `certificate_token`. With `restricted` or `projects`: `certificate_project`.

## 3. Identity

`name`, the client name in the token. An open token is a running operation with class `token` and that client name.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The client name. |
| `state` | str | `present` | no | `present` issues a token. `absent` revokes open tokens for `name`. |
| `restricted` | bool | `false` | no | The new certificate is restricted. |
| `projects` | list | | no | Projects for a restricted certificate. |
| `force` | bool | `false` | no | Issue a new token even if one is open. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

This is an action module for `present`. Rule R8.

| State | Case | Action |
|---|---|---|
| `present` | No open token, or `force` is true | `POST` with `name`, `type: client`, `token: true`, `restricted`, and `projects`. |
| `present` | An open token exists | No request. `changed: false`. No token in the result. |
| `absent` | Open tokens exist | `DELETE` each operation. |
| `absent` | No open token | No request. `changed: false`. |

The token string is the base64 encoding of the JSON in the operation metadata. The module builds it the same way as the `lxc` client.

## 7. Check and diff mode

Check mode sends no request. It reports the predicted change. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `token` | str | The token. Only when the module issues one. Secret. Rule R9. |
| `expires_at` | str | The expiry from the operation metadata. |
| `operation` | str | The operation ID. |

```yaml
token: eyJjbGllbnRfbmFtZSI6Im5ldy1jbGllbnQiLC...
expires_at: "2026-11-03T13:00:00Z"
operation: 01a1a00a-6ae7-7412-8972-aea8529f209b
```

## 9. Errors

| Case | Message |
|---|---|
| The server does not listen on the network. | The LXD error `Cannot issue token when server is not listening on network` |
| `projects` without `restricted`. | The LXD error. |

## 10. Cluster behavior

None. The module puts all member addresses in the token, as LXD returns them.

## 11. Tests

Fixture: `lxd/standalone`. It runs TT1 to TT4.

| ID | Goal | Pass when |
|---|---|---|
| TT1 | A new client adds itself with the token. | The new client gets `auth: trusted`. |
| TT2 | A second run does not issue a new token. | `changed` is false. |
| TT3 | `absent` revokes the token. | A join with the old token fails. |
| TT4 | A restricted token gives a restricted certificate. | The new entry has `restricted: true`. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should this module issue the new `auth/identities/tls` pending tokens instead? `lxd_auth_identity` with `pending` already covers that.
