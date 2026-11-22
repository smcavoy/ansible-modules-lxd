# lxd_image_export

## 1. Purpose

Download an image from the LXD image store to a directory on the controller.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/images/{fingerprint}` | `GET` | sync | Read the image and its fingerprint. |
| `/1.0/images/aliases/{name}` | `GET` | sync | Resolve an alias. |
| `/1.0/images/{fingerprint}/export` | `GET` | file or multipart | Download. A unified image comes as one file. A split image comes as a multipart body. |

Required API extensions: none beyond the base API.

## 3. Identity

`fingerprint` or `alias`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `fingerprint` | str | | no | A full fingerprint or a unique prefix. |
| `alias` | str | | no | An alias name. Mutually exclusive with `fingerprint`. |
| `project` | str | | no | The project. |
| `dest_dir` | path | | yes | A directory on the controller. |
| `force_download` | bool | `false` | no | Download again even if the files match. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

The module has no `state`. It makes sure that `dest_dir` holds the image files.

| Case | Action |
|---|---|
| The files in `dest_dir` match the fingerprint, and `force_download` is false | No download. `changed: false`. |
| A file does not exist, or a file differs | Download. `changed: true`. |

File names come from the `Content-Disposition` header of each part.
A unified image gives one file. A split image gives a metadata file and a rootfs file.
The fingerprint is the SHA-256 of the unified file, or of the metadata file followed by the rootfs file.
The module downloads to temporary files in `dest_dir`. It checks the SHA-256, then moves the files into place.

## 7. Check and diff mode

Check mode computes the SHA-256 of the existing files and reports the predicted change. It does not download.
The diff holds the list of files.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `fingerprint` | str | The full fingerprint. |
| `files` | list | The paths of the files in `dest_dir`. |

```yaml
fingerprint: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
files:
  - /srv/images/meta-32cc6e69adc3.tar.xz
  - /srv/images/32cc6e69adc3.squashfs
```

## 9. Errors

| Case | Message |
|---|---|
| `dest_dir` does not exist. | `dest_dir does not exist: <dest_dir>` |
| The SHA-256 of the download differs. | `downloaded files do not match fingerprint <fp>` |
| Neither `fingerprint` nor `alias`. | Ansible `required_one_of` error. |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. This module is not a resource module. It runs EX1 to EX4 only.

| ID | Goal | Pass when |
|---|---|---|
| EX1 | Export of a split image gives two files. | Both files exist. |
| EX2 | A second run makes no change. | `changed` is false. |
| EX3 | A changed file causes a new download. | `changed` is true. The SHA-256 matches again. |
| EX4 | The exported files import again. | `lxd_image` with `metadata_path` and `rootfs_path` gives the same fingerprint. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
