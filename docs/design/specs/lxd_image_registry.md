# lxd_image_registry

## 1. Purpose

Create, update, and delete image registries that instances and images use as sources.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/image-registries/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/image-registries` | `POST` | async | Create. |
| `/1.0/image-registries/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/image-registries/{name}` | `DELETE` | async | Delete. |

Required API extensions: `image_registries`. A registry of the LXD protocol needs a cluster link, so it also needs `cluster_links`.

## 3. Identity

`name`. Registries are global, not per project.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The registry name. It starts with a letter or a digit. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. See the protocol table. |
| `config_mode` | str | `merge` | no | Rule R4. |

LXD infers the protocol from `config`. The module has no `protocol` option:

| Protocol | Required keys | Forbidden keys |
|---|---|---|
| `simplestreams` | `url` | `cluster`, `source_project` |
| `lxd` | `cluster`, `source_project` | `url` |

The `url` value cannot hold a user name or a password. `user.*` keys are free.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST /1.0/image-registries` with `name`, `description`, and `config`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |
| The new config needs another protocol | Fail. The protocol cannot change. |
| A built-in registry | Fail on any change. Allow a read with no change. |

The built-in registries are `images`, `ubuntu`, `ubuntu-daily`, `ubuntu-minimal`, and `ubuntu-minimal-daily`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `image_registry` | dict | The registry from `GET`, after the change. `null` after a delete. |

```yaml
image_registry:
  name: mirror
  description: Local mirror
  protocol: simplestreams
  public: true
  builtin: false
  config:
    url: https://images.example.net
```

`public` is computed. A `simplestreams` registry is always public. An `lxd` registry is public when its cluster link type is `public`.

## 9. Errors

| Case | Message |
|---|---|
| Both `url` and `cluster`. | The LXD error `Image registry cannot have both a source URL and a cluster link` |
| Neither `url` nor `cluster`. | The LXD error `Image registry requires either a source URL ... or a cluster link ...` |
| An `lxd` registry without `source_project`. | The LXD error `No source project provided for a LXD image registry` |
| The cluster link does not exist. | The LXD error `Cluster link ... does not exist` |
| A change to a built-in registry. | `built-in image registry <name> cannot be changed` |
| A change of protocol. | `image registry protocol cannot change from <old> to <new>` |
| Delete a registry in use. | The LXD error `Image registry ... is in use by <n> image(s)` |

## 10. Cluster behavior

None. Registries are global.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_image_registry` | `lxd/standalone` | C1 to C12 for a `simplestreams` registry. IR1 to IR4. |
| `lxd_image_registry_lxd` | `lxd/multicluster` | IR5. |

| ID | Goal | Pass when |
|---|---|---|
| IR1 | A change to `images` fails. | `msg` holds `built-in`. No request is sent. |
| IR2 | A move from `url` to `cluster` fails. | `msg` holds `cannot change`. |
| IR3 | A `url` with a password fails. | The LXD error holds `Basic authentication`. |
| IR4 | A project with `restricted.registries: block` cannot use the registry. | An instance create from the registry fails. |
| IR5 | An `lxd` registry over a cluster link lists the images of the other cluster. | `lxd_image_registry_info` lists them. |

For C2 to C12, the registry `url` points to a local web server in the runner. It serves a small simplestreams index.

## 12. Hardware exceptions

None.

## 13. Open questions

1. Who builds the small simplestreams index for tests? This spec proposes a static index in `tests/lxd/simplestreams/`.
