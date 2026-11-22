# lxd_instance_log_info

## 1. Purpose

List the log files of an instance and read one of them.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/instances/{name}/logs` | `GET` | The list of log file URLs. |
| `/1.0/instances/{name}/logs/{filename}` | `GET` | One log file. |

Required API extensions: none beyond the base API.

## 3. Identity

`instance`, `project`, and, if set, `filename`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `project` | str | | no | The project. |
| `filename` | str | | no | One log file, for example `lxc.log` or `qemu.log`. Without it, the module lists the files. LXD accepts only `lxc.conf`, `qemu.conf`, and its own log names. |
| `tail` | int | | no | Return only the last lines. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.
A missing `filename` gives an empty `content` and an empty `lines`, not a failure.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `logs` | list | File names. |
| `content` | str | The file content, if `filename` is set. An empty string if the file does not exist. |
| `lines` | list | `content` split into lines. |

```yaml
logs:
  - lxc.log
  - lxc.conf
content: "lxc web1 20261103100000.123 INFO ..."
lines:
  - "lxc web1 20261103100000.123 INFO ..."
```

## 9. Errors

| Case | Message |
|---|---|
| A bad file name. | The LXD error `Log file name ... not valid` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. I1 to I4, and LG1. I3 asks for `qemu.conf` on a container, a valid name with no file. LXD refuses other names.

| ID | Goal | Pass when |
|---|---|---|
| LG1 | `tail: 5` returns at most 5 lines. | `lines` has 5 items or fewer. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
