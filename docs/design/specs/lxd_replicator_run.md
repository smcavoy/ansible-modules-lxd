# lxd_replicator_run

## 1. Purpose

Start a replicator run now, or restore from the replica.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/replicators/{name}/state` | `GET` | sync | Read `status`. |
| `/1.0/replicators/{name}/state` | `PUT` | async | Run, with `action: start` or `restore`. |

Required API extensions: `replicators`.

## 3. Identity

Not applicable. This is an action module. Rule R8.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The replicator. |
| `project` | str | | no | The project. |
| `mode` | str | `start` | no | `start` copies to the replica. `restore` copies back from the replica. The module sends it as `action`. |
| `wait` | bool | `true` | no | Wait for the run to end. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

| Case | Action |
|---|---|
| `status` is `Running` | No request. `changed: false`. A warning says that a run is in progress. |
| Otherwise | `PUT .../state` with `action` set to `mode`. With `wait`, wait for the operation. `changed: true`. |

The module always reports a change when it starts a run.

## 7. Check and diff mode

Check mode sends no request. It reports `changed: true` unless a run is in progress. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `status` | str | `Pending`, `Running`, `Completed`, or `Failed`, after the run or after the start. |
| `operation` | str | The operation ID. |

```yaml
status: Completed
operation: 01a1a00a-6ae7-7412-8972-aea8529f209b
```

## 9. Errors

| Case | Message |
|---|---|
| No cluster link in the config. | The LXD error `Replicator ... has no cluster link configured` |
| The run fails. | `LXD operation <id> failed: <err>` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/multicluster`. It runs RR1 to RR3.

| ID | Goal | Pass when |
|---|---|---|
| RR1 | `start` copies an instance to the other cluster. | The instance exists in the standby project on the other cluster. |
| RR2 | `restore` brings back a deleted file. | The source instance has the file again. |
| RR3 | Check mode does not start a run. | `last_run_at` does not change. |

## 12. Hardware exceptions

None for `dir` pools. Ceph mirroring is an exception.

## 13. Open questions

1. What does `restore` do to the source project while it runs? Test it in the first run and document the result.
   Answer from the test runs: the project here must be in `standby` mode with all instances stopped, and the other project in `leader` mode.
   A restore in LXD 6.10.1 looks for the instance profiles in the project itself, even with `features.profiles=false`, and fails with `Profile "default" not found`.
   LXD reports only `One or more child operations failed` on the parent operation. The module reads the children for the real error.
