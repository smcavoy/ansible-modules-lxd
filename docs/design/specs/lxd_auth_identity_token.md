# lxd_auth_identity_token

## 1. Purpose

Issue or revoke the token of a bearer identity.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/auth/identities/bearer/{name_or_id}` | `GET` | sync | Read the identity. |
| `/1.0/auth/identities/bearer/{name_or_id}/token` | `POST` | sync | Issue a token. A new token replaces the old one. |
| `/1.0/auth/identities/bearer/{name_or_id}/token` | `DELETE` | sync | Revoke the token. |

Required API extensions: `auth_bearer`.

## 3. Identity

`name` of the bearer identity.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The bearer identity. |
| `state` | str | `present` | no | `present` issues a token. `absent` revokes it. |
| `expiry` | str | | no | A duration, for example `24h` or `30d`. Empty means the server default. |
| `force` | bool | `false` | no | With `present`, issue a new token even if one exists. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

This is an action module for `present`. Rule R8.

| State | Case | Action |
|---|---|---|
| `present` | The identity type ends with `(pending)`, or `force` is true | `POST .../token`. `changed: true`. |
| `present` | The identity has a token, and `force` is false | No request. `changed: false`. No token in the result. |
| `absent` | The identity type ends with `(pending)` | No request. `changed: false`. |
| `absent` | The identity has a token | `DELETE .../token`. `changed: true`. |

LXD marks a bearer identity without a token with a type that ends with `(pending)`.

## 7. Check and diff mode

Check mode sends no request. It reports the predicted change. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `token` | str | The new token. Only when the module issues one. Secret. Rule R9. |
| `identity` | dict | The identity after the change. |

```yaml
token: eyJhbGciOiJFUzM4NCIs...
identity:
  name: ci-runner
  type: Client token bearer
  expires_at: "2026-11-04T10:00:00Z"
```

## 9. Errors

| Case | Message |
|---|---|
| The identity is not a bearer identity. | The LXD error `Token cannot be issued for identity of type ...` |
| The identity does not exist. | `bearer identity <name> not found` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. It runs IT1 to IT4.

| ID | Goal | Pass when |
|---|---|---|
| IT1 | A token works for a request. | `GET /1.0` with the token gives `auth: trusted`. |
| IT2 | A second run does not issue a new token. | `changed` is false. The old token still works. |
| IT3 | `force` issues a new token. | The old token fails. The new one works. |
| IT4 | `absent` revokes the token. | The token fails. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
