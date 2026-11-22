# lxd_auth_identity_provider_group

## 1. Purpose

Map a group name from an OIDC identity provider to LXD authorization groups.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/auth/identity-provider-groups/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/auth/identity-provider-groups` | `POST` | sync | Create. |
| `/1.0/auth/identity-provider-groups/{name}` | `PUT` | sync, checks `If-Match` | Update `groups`. |
| `/1.0/auth/identity-provider-groups/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `access_management`.

## 3. Identity

`name`, the group name from the identity provider claim.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The provider group name. |
| `state` | str | `present` | no | `present` or `absent`. |
| `groups` | list | | no | LXD group names. `null` means "do not manage". |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST` with `name` and `groups`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `groups`. |

The module compares `groups` as a set.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `groups`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `identity_provider_group` | dict | The mapping from `GET`. `null` after a delete. |

```yaml
identity_provider_group:
  name: lxd-admins
  groups:
    - admins
```

## 9. Errors

| Case | Message |
|---|---|
| A group that does not exist. | The LXD error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because mappings have no config.
The mapping needs no identity provider. Only a login through it needs one.

| ID | Goal | Pass when |
|---|---|---|
| IPG1 | Groups in another order make no change. | `changed` is false. |

## 12. Hardware exceptions

A login that uses the mapping needs an OIDC provider. Section 13 of the testing framework lists it.

## 13. Open questions

None.
