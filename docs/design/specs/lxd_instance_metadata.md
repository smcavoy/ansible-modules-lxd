# lxd_instance_metadata

## 1. Purpose

Manage the image metadata of an instance, including its template files.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}/metadata` | `GET` | sync, `ETag` | Read `metadata.yaml` as an object. |
| `/1.0/instances/{name}/metadata` | `PUT` | sync, ignores `If-Match` | Write `metadata.yaml`. |
| `/1.0/instances/{name}/metadata/templates?path=<p>` | `GET` | file | Read a template file. |
| `/1.0/instances/{name}/metadata/templates?path=<p>` | `POST` | sync | Write a template file. |
| `/1.0/instances/{name}/metadata/templates?path=<p>` | `DELETE` | sync | Delete a template file. |

Required API extensions: `container_edit_metadata`.

## 3. Identity

`instance` and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `project` | str | | no | The project. |
| `properties` | dict | | no | Metadata properties. `null` means "do not manage". |
| `properties_mode` | str | `merge` | no | `merge` or `exact`. |
| `templates` | list | | no | Template entries, each with the `path` in the instance. `null` means "do not manage". The first draft used a dict keyed by path. Ansible cannot check the sub-options of such a dict, so the module takes a list. |
| `templates_mode` | str | `merge` | no | `exact` removes template entries and files that are not in `templates`. |

Each template entry has:

| Field | Type | Rule |
|---|---|---|
| `path` | str | The path of the file in the instance. Required. |
| `when` | list | Events: `create`, `copy`, `start`, `rename`. |
| `create_only` | bool | Write the file only if it does not exist. |
| `template` | str | The template file name under `templates/`. |
| `properties` | dict | Template properties. |
| `content` | str | The template file content. The module writes it with the templates endpoint. |

## 5. Computed keys

`architecture`, `creation_date`, and `expiry_date` in `metadata.yaml`. The module never changes them.

## 6. Behavior per state

| Case | Action |
|---|---|
| Same | No request. `changed: false`. |
| Properties or entries differ | `PUT .../metadata` with the full object. Rule R3 says that the server does not check `If-Match`. |
| A template file differs | `POST .../templates?path=<template>` with the content. |
| `exact` and an extra template file | `DELETE .../templates?path=<file>`. |

The module compares template content by SHA-256.

## 7. Check and diff mode

The diff holds `properties`, the template entries, and the SHA-256 of each template file. Both sides hold the hashes of the files that the task names.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `metadata` | dict | The metadata after the change, without template content. |

```yaml
metadata:
  architecture: x86_64
  creation_date: 1762160000
  properties:
    description: Web server
  templates:
    /etc/hostname:
      when:
        - create
        - copy
      create_only: false
      template: hostname.tpl
      properties: {}
```

## 9. Errors

| Case | Message |
|---|---|
| An entry names a template with no file and no `content`. | `template <name> has no file and no content` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. It runs MD1 to MD4.

| ID | Goal | Pass when |
|---|---|---|
| MD1 | A `create` template writes a file in a copy. | A copy of the instance has the rendered file. |
| MD2 | A second run makes no change. | `changed` is false. |
| MD3 | `templates_mode: exact` removes an extra template. | The template file is gone. |
| MD4 | `properties` change the metadata. | `GET .../metadata` shows the new property. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. `PUT .../metadata` does not check `If-Match` in 6.10.1. Only `PATCH` does. Should the module use `PATCH` for lost-update protection? This spec uses `PUT`, like all modules.
