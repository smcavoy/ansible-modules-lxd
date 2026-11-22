# lxd_image_alias

## 1. Purpose

Create, update, and delete image aliases, apart from the images they point to.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/images/aliases/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/images/aliases` | `POST` | sync `201` | Create. |
| `/1.0/images/aliases/{name}` | `PUT` | sync, checks `If-Match` | Update `target` and `description`. |
| `/1.0/images/aliases/{name}` | `DELETE` | sync | Delete. |

Required API extensions: none beyond the base API.

## 3. Identity

`name` and `project`. The module does not rename aliases.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The alias name. It can hold `/`. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `target` | str | | yes for `present` | The image fingerprint. A unique prefix of at least 12 characters is allowed. |
| `description` | str | | no | `null` means "do not manage". |

## 5. Computed keys

None. LXD sets `type` from the target image.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/images/aliases` with `name`, `target`, and `description`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `target` and `description`. |

The module expands a fingerprint prefix with `GET /1.0/images/{prefix}` before it compares.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. The image stays. |

## 7. Check and diff mode

The diff holds `target` and `description`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `alias` | dict | The alias from `GET`, after the change. `null` after a delete. |

```yaml
alias:
  name: test/alpine-ct
  target: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
  type: container
  description: Pinned Alpine
```

## 9. Errors

| Case | Message |
|---|---|
| `target` does not exist. | `image <target> not found` |
| `state: present` without `target`. | Ansible `required_if` error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because aliases have no config.

| ID | Goal | Pass when |
|---|---|---|
| IA1 | A move of the alias to another image. | `target` is the new fingerprint. |
| IA2 | A fingerprint prefix equals the full fingerprint. | `changed` is false. |
| IA3 | A delete of the alias keeps the image. | The image still exists. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
