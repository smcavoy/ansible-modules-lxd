# lxd_image_info

## 1. Purpose

Read images in the LXD image store by fingerprint, alias, or filter.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/images?recursion=1` | `GET` | All images in the project. With `filter`, the matching images. |
| `/1.0/images/{fingerprint}` | `GET` | One image. |
| `/1.0/images/aliases/{name}` | `GET` | Resolve an alias. |

Required API extensions: none. With `all_projects`: `images_all_projects`. With `filter`: `api_filtering`.

## 3. Identity

`fingerprint`, `alias`, or `filter`. At most one of them.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `fingerprint` | str | | no | A full fingerprint or a unique prefix. |
| `alias` | str | | no | An alias name. |
| `filter` | str | | no | An LXD filter expression, for example `properties.os eq Alpine`. |
| `project` | str | | no | The project. |
| `all_projects` | bool | `false` | no | Images in all projects. Mutually exclusive with `project`. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `images` | list | Each item is an image object with `project`. |

```yaml
images:
  - fingerprint: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
    type: container
    aliases:
      - name: test/alpine-ct
        description: ""
    properties:
      os: Alpine
    project: default
```

## 9. Errors

| Case | Message |
|---|---|
| More than one of `fingerprint`, `alias`, `filter`. | Ansible `mutually_exclusive` error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4, with `alias` for I2 and I3.

| ID | Goal | Pass when |
|---|---|---|
| II1 | A fingerprint prefix finds one image. | Exactly one result. |
| II2 | `filter` by `properties.os` finds the Alpine images. | Every item has `os: Alpine`. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
