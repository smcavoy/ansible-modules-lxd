# lxd_instance_device

## 1. Purpose

Manage one device on an instance that another tool or task owns.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}` | `GET` | sync, `ETag` | Read the instance devices. |
| `/1.0/instances/{name}` | `PUT` | async, checks `If-Match` | Write the full instance with the changed device. |

Required API extensions: `instances`.

## 3. Identity

`instance`, `name`, and `project`. `name` is the device name.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `name` | str | | yes | The device name. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `properties` | dict | | yes for `present` | The device properties, with `type`. Values become strings. |
| `allow_restart` | bool | `false` | no | Restart the instance if LXD cannot add or change the device live. |

## 5. Computed keys

None. The module compares only the one device.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | Read the instance. Add the device. `PUT` the full instance with the read `ETag`. |
| Present, same | No request. `changed: false`. |
| Present, different | Replace the device with `properties`. `PUT`. |

The module sends back every other field as it read it. On `412`, it reads again and applies only its device. Rule R3.
A device with the same name in a profile does not count. An instance device overrides it.
With `allow_restart: true`, the restart rule in the `lxd_instance` spec applies.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | Remove the device. `PUT`. |

## 7. Check and diff mode

The diff holds the one device.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `device` | dict | The device after the change. `null` after a delete. |
| `instance` | str | The instance name. |

```yaml
instance: web1
device:
  type: proxy
  listen: tcp:0.0.0.0:8080
  connect: tcp:127.0.0.1:80
```

## 9. Errors

| Case | Message |
|---|---|
| The instance does not exist. | `instance <name> not found` |
| `properties` without `type`. | `properties needs type` |
| LXD cannot hot-plug the device. | The LXD error, unless `allow_restart` is true. |

## 10. Cluster behavior

None. LXD sends the request to the member of the instance.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because there is no config map.

| ID | Goal | Pass when |
|---|---|---|
| DV1 | A `proxy` device on a running container forwards a port. | `curl` to the listen port works. |
| DV2 | The module keeps a device that another task added. | The other device stays. |
| DV3 | A device in a profile with the same name stays in the profile. | The profile is unchanged. |

## 12. Hardware exceptions

`gpu`, `pci`, `usb`, and `infiniband` device types. Test them on a stopped instance only.

## 13. Open questions

None.
