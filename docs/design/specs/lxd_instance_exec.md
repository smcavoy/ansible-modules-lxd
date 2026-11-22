# lxd_instance_exec

## 1. Purpose

Run a command in an instance and return its exit code and output.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}/exec` | `POST` | async | Run, with `record-output: true` and `wait-for-websocket: false`. |
| `/1.0/instances/{name}/logs/exec-output/{file}` | `GET` | file | Read stdout and stderr. |
| `/1.0/instances/{name}/logs/exec-output/{file}` | `DELETE` | sync | Remove the output files. |
| `/1.0/instances/{name}/files?path=<p>` | `HEAD` | sync | Check `creates` and `removes`. |

Required API extensions: `container_exec_recording`. With `user`, `group`, or `cwd`: `container_exec_user_group_cwd`.

## 3. Identity

Not applicable. This is an action module. Rule R8.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | A running instance. |
| `project` | str | | no | The project. |
| `command` | list | | yes | The command and its arguments. No shell, unless the list starts with a shell. |
| `environment` | dict | | no | Environment variables. |
| `user` | int | | no | The user ID. |
| `group` | int | | no | The group ID. |
| `cwd` | str | | no | The working directory. |
| `creates` | str | | no | A path in the instance. If it exists, the command does not run. |
| `removes` | str | | no | A path in the instance. If it does not exist, the command does not run. An instance that does not exist fails the task. |
| `ok_rc` | list of int | `[0]` | no | Exit codes that count as success. |

The module has no stdin support. The API needs a websocket for stdin.

## 5. Computed keys

Not applicable.

## 6. Behavior per state

| Case | Action |
|---|---|
| `creates` exists, or `removes` does not exist | No request. `changed: false`. `skipped_reason` says why. |
| Otherwise | `POST .../exec`. Wait for the operation. Read `metadata.return` and `metadata.output`. |
| After the run | `GET` both output files. Then `DELETE` them. |
| Exit code not in `ok_rc` | `failed: true`. The result still holds `rc`, `stdout`, and `stderr`. |

The module always reports `changed: true` when the command runs.

## 7. Check and diff mode

Check mode does not run the command. It checks `creates` and `removes`, and reports the predicted `changed`. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `rc` | int | The exit code. |
| `stdout` | str | The standard output. |
| `stderr` | str | The standard error. |
| `stdout_lines` | list | `stdout` split into lines. |
| `stderr_lines` | list | `stderr` split into lines. |

```yaml
rc: 0
stdout: "Alpine Linux 3.22\n"
stderr: ""
stdout_lines:
  - Alpine Linux 3.22
stderr_lines: []
```

## 9. Errors

| Case | Message |
|---|---|
| The instance does not run. | The LXD error `Instance is not running` |
| The instance is frozen. | The LXD error `Instance is frozen` |
| The exit code is not in `ok_rc`. | `command exited with code <rc>` |

## 10. Cluster behavior

None. LXD sends the request to the member of the instance.

## 11. Tests

Fixture: `lxd/standalone`. This is an action module. It runs EXC1 to EXC6.

| ID | Goal | Pass when |
|---|---|---|
| EXC1 | `cat /etc/os-release` returns output. | `rc` is 0. `stdout` holds `Alpine`. |
| EXC2 | A failing command fails the task. | `failed` is true. `rc` is not 0. |
| EXC3 | `ok_rc: [0, 1]` accepts exit code 1. | `failed` is false. |
| EXC4 | `creates` skips the command. | `changed` is false. |
| EXC5 | Check mode does not run the command. | A marker file does not exist after the task. |
| EXC6 | The output files are gone after the run. | `GET .../logs/exec-output` lists none. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.

## 14. Findings from the tests

1. LXD turns the exit code 127 into a failed operation with the error `Command not found`, and 126 into `not executable`.
   This also happens when a shell runs the command and passes the code on. The module returns these codes as `rc`.
2. Alpine busybox has no `httpd` applet. A test web server uses the `nc` applet.
