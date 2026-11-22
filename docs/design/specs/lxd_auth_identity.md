# lxd_auth_identity

## 1. Purpose

Create, update, and delete TLS, bearer, and OIDC identities, and set their groups.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/auth/identities/{type}/{name_or_id}` | `GET` | sync, `ETag` | Read. `{type}` is `tls`, `bearer`, or `oidc`. |
| `/1.0/auth/identities/tls` | `POST` | sync | Create from a certificate, or a pending identity with a join token. |
| `/1.0/auth/identities/bearer` | `POST` | sync `201` | Create a bearer identity. |
| `/1.0/auth/identities/{type}/{name_or_id}` | `PUT` | sync, checks `If-Match` | Update `groups`, and `tls_certificate` for TLS. |
| `/1.0/auth/identities/{type}/{name_or_id}` | `DELETE` | sync | Delete. |

Required API extensions: `access_management_tls` for TLS. `auth_bearer` for bearer. `access_management` for OIDC.

## 3. Identity

`type` and `name`. LXD also accepts the identifier: the fingerprint for TLS, or the ID for bearer and OIDC.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `type` | str | | yes | `tls`, `bearer`, or `oidc`. |
| `name` | str | | yes | The identity name. For `oidc`, the email or the identifier. |
| `state` | str | `present` | no | `present` or `absent`. |
| `groups` | list | | no | Group names. `null` means "do not manage". |
| `certificate` | str | | no | For `tls`. A PEM certificate. Create, or replace with `tls_certificate`. |
| `pending` | bool | `false` | no | For `tls`, create-only. Make a pending identity and return a join token. |
| `bearer_type` | str | `client` | no | For `bearer`, create-only. `client` or `devlxd`. |

`oidc` identities exist only after a login. The module cannot create them. It can set their groups or delete them.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| `tls`, absent, with `certificate` | `POST .../tls` with `name`, `certificate`, and `groups`. |
| `tls`, absent, `pending: true` | `POST .../tls` with `name`, `token: true`, and `groups`. Return the token. |
| `bearer`, absent | `POST .../bearer` with `name`, `type`, and `groups`. The module sends `Client token bearer` or `DevLXD token bearer`. |
| `oidc`, absent | Fail. |
| Present, same | No request. `changed: false`. |
| Present, different `groups` | `PUT` with `groups`. |
| `tls`, present, different `certificate` | `PUT` with `tls_certificate`. |

The module compares `groups` as a set. It compares `certificate` by fingerprint.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `groups` and the certificate fingerprint.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `identity` | dict | The identity from `GET`, after the change. `null` after a delete. |
| `join_token` | str | Only for `pending: true`, on the run that creates it. Secret. Rule R9. |

```yaml
identity:
  type: Client certificate
  authentication_method: tls
  id: 0ab1c2d3e4f5...
  name: alice
  groups:
    - web-operators
  expires_at: null
join_token: eyJjbGllbnRfbmFtZSI6...
```

## 9. Errors

| Case | Message |
|---|---|
| `oidc` and absent. | `OIDC identities exist only after a login` |
| `tls`, absent, with neither `certificate` nor `pending`. | `certificate or pending is required to create a TLS identity` |
| `certificate` and `pending` together. | Ansible `mutually_exclusive` error. |
| The certificate is already trusted. | The LXD error `Client already trusted` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12 for `tls`. Skip C6 to C8, because identities have no config.

| ID | Goal | Pass when |
|---|---|---|
| AID1 | A pending TLS identity returns a token. | `join_token` is set. The identity type ends with `(pending)`. |
| AID2 | A new client joins with the token. | The new client gets `auth: trusted`. |
| AID3 | A bearer identity with a group. | The identity has the group. |
| AID4 | Groups in another order make no change. | `changed` is false. |
| AID5 | `oidc` create fails. | `msg` holds `login`. |

## 12. Hardware exceptions

OIDC identities need an identity provider. See section 13 of the testing framework.

## 13. Open questions

None.

## 14. Findings from the tests

1. A restricted identity that asks for a project outside its groups gets `Not Found`, not `Forbidden`.
2. LXD can reset the connection right after a change to an identity. The client sends a `GET` once more after a connection error.
