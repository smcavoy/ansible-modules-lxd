# lxd_image

## 1. Purpose

Get images into the LXD image store from a registry, an instance, or a file, and manage their properties.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/images/{fingerprint}` | `GET` | sync, `ETag` | Read. |
| `/1.0/images/aliases/{name}` | `GET` | sync | Find an image by alias. |
| `/1.0/images` | `POST` JSON | async | Copy from a registry, or publish an instance or a snapshot. |
| `/1.0/images` | `POST` binary | async | Upload a unified tarball. |
| `/1.0/images` | `POST` multipart | async | Upload a split image: parts `metadata` and `rootfs`, or `rootfs.img` for a VM. |
| `/1.0/images/{fingerprint}` | `PUT` | sync, checks `If-Match` | Update the managed fields. |
| `/1.0/images/{fingerprint}` | `DELETE` | async | Delete. |
| `/1.0/images/aliases` | `POST` | sync | Add an alias. |
| `/1.0/images/aliases/{name}` | `DELETE` | sync | Remove an alias. |

Required API extensions: `image_registries` for a registry source. `image_create_aliases` for `aliases` on create.
`images_expiry` for `expires_at`. `image_profiles` for `profiles`. `image_compression_algorithm` for `compression_algorithm`.

## 3. Identity

The module finds the image by `fingerprint`. Without `fingerprint`, it finds the image by the first name in `aliases`.
`project` scopes the search. The project needs `features.images` for its own images.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `fingerprint` | str | | no | The full fingerprint, or a unique prefix of at least 12 characters. |
| `aliases` | list of dict | | no | Each item has `name` and `description`. `null` means "do not manage". |
| `aliases_mode` | str | `merge` | no | `merge` adds aliases. `exact` also removes aliases that point to this image and are not in the list. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `source` | dict | | no | Used only when the image is absent. See the source table. |
| `properties` | dict | | no | Image properties. `null` means "do not manage". |
| `properties_mode` | str | `merge` | no | `merge` or `exact`, like rule R4. |
| `public` | bool | | no | Only the `default` project accepts `true`. |
| `auto_update` | bool | | no | Only for images from a registry. |
| `profiles` | list | | no | Profiles for instances from this image. |
| `expires_at` | str | | no | An RFC 3339 time, or `""`. LXD 6.10.1 cannot remove the expiry date of an image: the module fails when the task gives `""` and the image has a date. |
| `compression_algorithm` | str | | no | Create-only, for a publish. |

Source forms. `source` holds exactly one form:

| Form | Keys | Request |
|---|---|---|
| Registry | `image_registry`, `alias` or `fingerprint`, `image_type`, `copy_aliases` | JSON with `source.type: image` and `source.mode: pull`. |
| Instance | `instance`, optional `snapshot` | JSON with `source.type: instance` or `snapshot`. |
| Unified file | `path` | Binary body with `X-LXD-filename`, `X-LXD-public`, `X-LXD-properties`, `X-LXD-profiles`. |
| Split file | `metadata_path`, `rootfs_path` | Multipart body. The rootfs part is `rootfs.img` when `image_type` is `virtual-machine`. |
| Other project | `project`, `alias` or `fingerprint` | JSON with `source.type: image` and `source.project`, without a registry. |

`image_type` is `container` or `virtual-machine`.

## 5. Computed keys

The registry and the server set properties such as `os`, `release`, `architecture`, `serial`, and `description`.
With `properties_mode: merge`, these keys stay. With `exact`, the module removes keys that are not in the task.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent, with `source` | The request for the source form. Read the fingerprint from the operation metadata. Then apply the managed fields and the aliases. |
| Absent, no `source` | Fail. The module cannot find or make the image. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full image object. Add or remove aliases with the alias endpoints. |

An image from a registry with `alias` can get a new fingerprint upstream. The module does not refresh it.
It compares only by the local alias or the fingerprint.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. LXD removes its aliases too. |

## 7. Check and diff mode

The diff holds `aliases`, `properties`, `public`, `auto_update`, `profiles`, and `expires_at`.
On create in check mode, `after.fingerprint` is `unknown` unless the task sets it.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `image` | dict | The image from `GET`, after the change. `null` after a delete. |

```yaml
image:
  fingerprint: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
  type: container
  architecture: x86_64
  public: false
  auto_update: false
  size: 3145728
  aliases:
    - name: test/alpine-ct
      description: ""
  properties:
    os: Alpine
    release: "3.22"
  profiles:
    - default
  expires_at: "0001-01-01T00:00:00Z"
```

## 9. Errors

| Case | Message |
|---|---|
| `public: true` in a project other than `default`. | `public images are only allowed in the default project` |
| Absent and no `source`. | `image not found and no source given` |
| A `server` that is not a registry. | The LXD error `No image registry found for image source server ...` |
| An alias already points to another image. | The LXD error `Alias ... already exists`. The module adds the other fingerprint. |
| A fingerprint prefix that matches two images. | `fingerprint prefix <p> matches more than one image` |

## 10. Cluster behavior

None. LXD replicates images to members by itself.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5, C9 to C12, with `properties` as config for C6 to C8.

| ID | Goal | Pass when |
|---|---|---|
| IM1 | Upload a unified tarball. | The fingerprint matches `tests/lxd/images.yml`. |
| IM2 | Upload a split VM image. | `type` is `virtual-machine`. |
| IM3 | Publish a stopped container. | A new image exists with the given alias. |
| IM4 | `aliases_mode: exact` removes an extra alias. | The alias is gone. |
| IM5 | `public: true` in a test project fails early. | `msg` holds `default project`. |
| IM6 | Copy from the `images` registry. This case needs the alias `lxd/needs/internet`. | The image exists. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should the module offer `refresh: true` for registry images? The plan leaves `POST .../refresh` for a later release.

## 14. Findings from the tests

1. An alias without `description` keeps its current description. Before this fix, the default `""` reset it.
2. A container publish gives a unified image. The `images` registry gives split images.
   The IM1 test exports a published image to get a unified tarball.
