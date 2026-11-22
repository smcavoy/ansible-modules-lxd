# lxd_trust_certificate

## 1. Purpose

Manage entries in the legacy trust store, including certificates restricted to projects.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/certificates/{fingerprint}` | `GET` | sync, `ETag` | Read. |
| `/1.0/certificates` | `POST` | sync | Add a certificate. |
| `/1.0/certificates/{fingerprint}` | `PUT` | sync, checks `If-Match` | Update `name`, `type`, `restricted`, and `projects`. |
| `/1.0/certificates/{fingerprint}` | `DELETE` | sync | Remove. |

Required API extensions: `certificate_update`. With `restricted` or `projects`: `certificate_project`.

## 3. Identity

The SHA-256 fingerprint of `certificate`, or `fingerprint`. `name` is not unique, so the module does not find entries by name.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `certificate` | str | | no | A PEM certificate. Required to add. |
| `fingerprint` | str | | no | Find an existing entry. Required for `absent` without `certificate`. |
| `name` | str | | no | The entry name. It cannot start with `-` or hold `/`. |
| `state` | str | `present` | no | `present` or `absent`. |
| `type` | str | `client` | no | `client` or `metrics`. |
| `restricted` | bool | `false` | no | Limit the certificate to `projects`. |
| `projects` | list | | no | Project names. Only with `restricted: true`. |

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/certificates` with `name`, `type`, `certificate`, `restricted`, and `projects`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `name`, `type`, `restricted`, and `projects`. |

The module compares `projects` as a set.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

The module refuses to remove the certificate that the task itself uses. That would lock the task out.

## 7. Check and diff mode

The diff holds `name`, `type`, `restricted`, and `projects`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `certificate` | dict | The entry from `GET`, after the change. `null` after a delete. |

```yaml
certificate:
  name: lxdtest-runner
  type: client
  restricted: true
  projects:
    - ci-tests
  fingerprint: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

## 9. Errors

| Case | Message |
|---|---|
| `projects` without `restricted: true`. | The LXD error `Projects can only be specified for restricted certificates ...` |
| Remove the certificate of this task. | `refusing to remove the certificate that this task uses` |
| Remove a server certificate. | The LXD error `Cannot delete a server certificate. Remove the cluster member instead` |
| A bad PEM. | `certificate is not a valid PEM certificate` |

## 10. Cluster behavior

None. The trust store is global.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because certificates have no config.

| ID | Goal | Pass when |
|---|---|---|
| TC1 | A restricted certificate sees only its project. | A request for project `default` with it fails with `Certificate is restricted`. |
| TC2 | The module refuses to remove its own certificate. | `msg` holds `refusing`. The entry stays. |
| TC3 | Projects in another order make no change. | `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should the collection deprecate this module in favor of `lxd_auth_identity`? The plan keeps it for restricted certificates.
