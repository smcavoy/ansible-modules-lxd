# lxd_warning

## 1. Purpose

Acknowledge, reset, or delete one LXD warning.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/warnings/{uuid}` | `GET` | sync | Read. No `ETag`. |
| `/1.0/warnings/{uuid}` | `PUT` | sync, ignores `If-Match` | Set `status`. |
| `/1.0/warnings/{uuid}` | `DELETE` | sync | Delete. |

Required API extensions: `warnings`.

## 3. Identity

`uuid`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `uuid` | str | | yes | The warning UUID. |
| `state` | str | `present` | no | `present` or `absent`. |
| `status` | str | | no | `new` or `acknowledged`. `null` means "do not manage". |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | Fail. A module cannot create a warning. |
| Same `status` | No request. `changed: false`. |
| Different `status` | `PUT` with `status`. |

LXD can also set `status: resolved`. The module treats it as a read-only value.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. LXD makes a new warning if the cause comes back. |

## 7. Check and diff mode

The diff holds `status`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `warning` | dict | The warning from `GET`, after the change. `null` after a delete. |

```yaml
warning:
  uuid: e9f1...
  type: Couldn't find the CGroup memory swap accounting
  severity: low
  status: acknowledged
  count: 1
  location: none
  project: ""
  last_message: ""
```

## 9. Errors

| Case | Message |
|---|---|
| `present` on a missing warning. | `warning <uuid> not found` |
| `status: resolved`. | Ansible `choices` error. LXD allows only `new` and `acknowledged`. |

## 10. Cluster behavior

None. Each warning has `location`.

## 11. Tests

Fixture: `lxd/standalone`. It runs W1 to W4 on a warning that the sandbox has.
The standard cases do not apply, because a task cannot create a warning. W1 to W4 cover the update and the delete.
If the sandbox has no warning, the target skips with the reason "no warning on the server".

| ID | Goal | Pass when |
|---|---|---|
| W1 | `status: acknowledged`. | The server shows `acknowledged`. |
| W2 | A second run makes no change. | `changed` is false. |
| W3 | `status: new` resets it. | The server shows `new`. |
| W4 | `absent` deletes it. | The warning is gone. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. A sandbox may have no warning. Can a test make one on purpose? Find a safe trigger in the first run.
