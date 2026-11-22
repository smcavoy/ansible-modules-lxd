# lxd_profile

## 1. Purpose

Create, update, and delete LXD profiles, with their config, devices, and description.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/profiles/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/profiles` | `POST` | sync `201` | Create. |
| `/1.0/profiles/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/profiles/{name}` | `DELETE` | sync | Delete. |

Required API extensions: none beyond the base API. `storage_and_profile_operations` makes `PUT` async. Rule R2 covers both cases.

## 3. Identity

`name` and `project`. The module does not rename profiles.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The profile name. It cannot hold `/`. |
| `project` | str | | no | The project. The project needs `features.profiles`, or LXD uses the `default` project profiles. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Instance config keys. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `devices` | dict | | no | Rule R5. |
| `devices_mode` | str | `merge` | no | Rule R5. |

## 5. Computed keys

None. Profiles hold no `volatile.*` keys.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/profiles` with `name`, `description`, `config`, and `devices`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. LXD applies the change to every instance that uses the profile. |

LXD saves the profile even if the change fails on some instances.
Then it returns an error that starts with `The following instances failed updating`.
The module reports `changed: true` and `failed: true`, and it puts the LXD error in `msg`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `config`, and `devices`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `profile` | dict | The profile from `GET`, after the change. `null` after a delete. |

```yaml
profile:
  name: web
  project: default
  description: Web server profile
  config:
    limits.cpu: "2"
  devices:
    eth0:
      type: nic
      network: lxdbr0
      name: eth0
  used_by:
    - /1.0/instances/web1
```

## 9. Errors

| Case | Message |
|---|---|
| Delete the `default` profile. | The LXD error `The "default" profile cannot be deleted` |
| Delete a profile in use. | The LXD error `Profile is currently in use` |
| A change fails on some instances. | The LXD error, with `changed: true`. |
| A device without `type`. | `device <name> needs a type` |

## 10. Cluster behavior

None. Profiles are global in a cluster.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C12, for `config` and for `devices`.

| ID | Goal | Pass when |
|---|---|---|
| PR1 | `devices_mode: exact` removes an unmanaged device. | The device is gone. |
| PR2 | A device change replaces the whole device. | The server device equals the task device. |
| PR3 | A profile change reaches a running instance. | The instance `expanded_config` has the new key. |
| PR4 | Delete of a profile in use fails. | `msg` holds `in use`. |

## 12. Hardware exceptions

GPU, USB, PCI, and InfiniBand devices in a profile. Test them only as config, without an instance start.

## 13. Open questions

None.
