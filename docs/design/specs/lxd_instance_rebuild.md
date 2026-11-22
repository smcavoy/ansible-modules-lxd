# lxd_instance_rebuild

## 1. Purpose

Rebuild an instance root disk from an image, or as an empty disk, and keep its config.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}` | `GET` | sync | Read the run state. |
| `/1.0/instances/{name}/state` | `PUT` | async | Stop before, and start after. |
| `/1.0/instances/{name}/rebuild` | `POST` | async | Rebuild. |

Required API extensions: `instances_rebuild`. A registry source needs `image_registries`.

## 3. Identity

Not applicable. This is an action module. Rule R8.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `project` | str | | no | The project. |
| `source` | dict | | yes | `image` with optional `image_registry`, or `empty: true`. |
| `force` | bool | `false` | no | Stop a running instance first. |
| `start` | bool | | no | Start the instance after the rebuild. Default: start it if it ran before. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

| Case | Action |
|---|---|
| Stopped | `POST .../rebuild` with `source.type: image` or `none`. |
| Running, `force: true` | Stop, rebuild, then start if `start` is true. |
| Running, `force: false` | Fail. |

The module always reports `changed: true` when it rebuilds.

## 7. Check and diff mode

Check mode does not rebuild. It reports `changed: true`. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `instance` | dict | The instance after the rebuild. |

```yaml
instance:
  name: web1
  status: Running
  config:
    volatile.base_image: 32cc6e69adc3...
```

## 9. Errors

| Case | Message |
|---|---|
| Running and no `force`. | `instance <name> runs. Set force to stop it before the rebuild.` |
| The image does not exist. | The LXD error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. It runs RB1 to RB3.

| ID | Goal | Pass when |
|---|---|---|
| RB1 | A rebuild removes a file from the root disk. | The file does not exist after the rebuild. |
| RB2 | A rebuild keeps the instance config. | `limits.cpu` is unchanged. |
| RB3 | A running instance without `force` fails. | `msg` holds `force`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
