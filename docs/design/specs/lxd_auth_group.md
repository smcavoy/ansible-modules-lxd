# lxd_auth_group

## 1. Purpose

Create, update, and delete authorization groups with their permissions.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/auth/groups/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/auth/groups` | `POST` | sync `201` | Create. |
| `/1.0/auth/groups/{name}` | `PUT` | sync, checks `If-Match` | Update `description` and `permissions`. |
| `/1.0/auth/groups/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `access_management`.

## 3. Identity

`name`. Groups are global.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The group name. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `permissions` | list of dict | | no | Each item has `entity_type`, `url`, and `entitlement`. `null` means "do not manage". |
| `permissions_mode` | str | `exact` | no | `exact` sets the list. `merge` adds the items and keeps the others. |

Example permission: `{entity_type: project, url: /1.0/projects/web, entitlement: operator}`.
The module accepts `url` with or without the `?project=` query. It compares the normalized form.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/auth/groups` with `name`, `description`, and `permissions`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `description` and `permissions`. |

The module compares `permissions` as a set.
Group members are not managed here. `lxd_auth_identity` sets the groups of an identity.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `permissions`, sorted.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `auth_group` | dict | The group from `GET`, with `identities` and `identity_provider_groups`. `null` after a delete. |

```yaml
auth_group:
  name: web-operators
  description: Operators of the web project
  permissions:
    - entity_type: project
      url: /1.0/projects/web
      entitlement: operator
  identities:
    tls:
      - alice
  identity_provider_groups: []
```

## 9. Errors

| Case | Message |
|---|---|
| A permission for an entity that does not exist. | The LXD validation error. |
| A permission other than server admin on `admins`. | The LXD error `The admins group can only be granted the server admin permission` |
| A bad entitlement for the entity type. | The LXD validation error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because groups have no config.

| ID | Goal | Pass when |
|---|---|---|
| AG1 | Permissions in another order make no change. | `changed` is false. |
| AG2 | `permissions_mode: merge` keeps a permission that the API added. | The old permission stays. |
| AG3 | A member identity gets the access. | A request with the identity certificate to the project gives `200`. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `permissions_mode` default to `exact`, as here, or to `merge`, like `config_mode`? A permission list is a security boundary, so this spec uses `exact`.
