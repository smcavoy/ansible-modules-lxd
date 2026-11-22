# lxd_auth_info

## 1. Purpose

Read identities, groups, provider group mappings, the current identity, and the available permissions.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/auth/identities?recursion=1` | `GET` | All identities. |
| `/1.0/auth/identities/{type}/{name_or_id}/state` | `GET` | `effective_groups` of one identity. Needs `access_management_identity_effective_groups`. |
| `/1.0/auth/identities/current` | `GET` | The identity of this client, with effective permissions. |
| `/1.0/auth/groups?recursion=1` | `GET` | All groups. |
| `/1.0/auth/identity-provider-groups?recursion=1` | `GET` | All provider group mappings. |
| `/1.0/auth/permissions?recursion=1` | `GET` | Permissions, filtered by `entity-type` and `project`. |

Required API extensions: `access_management`.

## 3. Identity

Not applicable. `gather` selects the parts.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `gather` | list | `[current]` | no | Any of `current`, `identities`, `groups`, `identity_provider_groups`, `permissions`. |
| `identity_type` | str | | no | Keep only identities of this method: `tls`, `bearer`, or `oidc`. |
| `include_effective_groups` | bool | `false` | no | Add `effective_groups` to each identity. One extra request per identity. |
| `entity_type` | str | | no | Filter for `permissions`, for example `project` or `instance`. |
| `project` | str | | no | Filter for `permissions`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `current` | dict | The current identity, with `effective_groups` and `effective_permissions`. |
| `identities` | list | Identity objects. |
| `groups` | list | Group objects. |
| `identity_provider_groups` | list | Mapping objects. |
| `permissions` | list | Each item has `entity_type`, `url`, `entitlement`, and `groups`. |

```yaml
current:
  name: ansible
  authentication_method: tls
  fine_grained: true
  effective_groups:
    - admins
identities:
  - name: alice
    authentication_method: tls
    groups:
      - web-operators
```

## 9. Errors

Only the shared errors in section 4 of the README.

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. I1, I4, and AU1 to AU3. Skip I2 and I3, because the module has no name filter.

| ID | Goal | Pass when |
|---|---|---|
| AU1 | `current` shows the test client. | `current.authentication_method` is `tls`. |
| AU2 | `include_effective_groups` shows a group from a provider mapping. | The group is in `effective_groups`. |
| AU3 | `permissions` with `entity_type: project` lists only projects. | Every item has `entity_type: project`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
