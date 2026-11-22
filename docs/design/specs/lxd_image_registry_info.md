# lxd_image_registry_info

## 1. Purpose

Read image registries and, on request, the images that a registry offers.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0/image-registries?recursion=1` | `GET` | All registries. |
| `/1.0/image-registries/{name}` | `GET` | One registry. |
| `/1.0/image-registries/{name}/images` | `GET` | The images that the registry offers. |

Required API extensions: `image_registries`.

## 3. Identity

`name`, if set. Without `name`, all registries.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | no | One registry. A missing registry gives an empty list. |
| `include_images` | bool | `false` | no | Add `images` to the registry. Needs `name`. |
| `image_filter` | dict | | no | Keep only images whose fields match, for example `{"properties.os": "Alpine", "type": "container"}`. The module filters on the client. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module only reads. It never reports a change.

The image list of a public registry can be large. The module filters it before it returns.

## 7. Check and diff mode

Check mode gives the same result. No diff.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `image_registries` | list | Each item is a registry object. With `include_images`, it has `images`. |

```yaml
image_registries:
  - name: images
    protocol: simplestreams
    builtin: true
    public: true
    config:
      url: https://images.lxd.canonical.com
    images:
      - fingerprint: 0f3c...
        type: container
        aliases:
          - name: alpine/3.22
        properties:
          os: Alpine
```

## 9. Errors

| Case | Message |
|---|---|
| `include_images` without `name`. | `include_images needs name` |
| The registry does not answer. | The LXD error `Failed loading images from image registry ...` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases I1 to I4.

| ID | Goal | Pass when |
|---|---|---|
| IRI1 | The built-in registries show `builtin: true`. | All five names are in the list. |
| IRI2 | `include_images` with `image_filter` on the local test registry. | Only matching images return. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `image_filter` use the LXD filter syntax instead of a dictionary? The registry endpoint has no server filter, so this spec uses a dictionary.
