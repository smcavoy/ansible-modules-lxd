# lxd_instance_file

## 1. Purpose

Put a file, a directory, or a symlink into an instance, or remove it, with owner and mode.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}/files?path=<p>` | `HEAD` | sync | Read type, owner, and mode without content. Needs `instance_file_head`. |
| `/1.0/instances/{name}/files?path=<p>` | `GET` | file | Read content and metadata. |
| `/1.0/instances/{name}/files?path=<p>` | `POST` | sync | Write. Headers `X-LXD-type`, `X-LXD-uid`, `X-LXD-gid`, `X-LXD-mode`, `X-LXD-write`. |
| `/1.0/instances/{name}/files?path=<p>` | `DELETE` | sync | Delete. Needs `file_delete`. |

Required API extensions: `file_delete`, `instance_file_head`. With `type: link`: `file_symlinks`.
A change of owner or mode on an existing file without new content needs `instances_files_modify_permissions`.

## 3. Identity

`instance`, `path`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. It must run, or be a stopped container. |
| `path` | str | | yes | The absolute path in the instance. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `type` | str | `file` | no | `file`, `directory`, or `link`. LXD calls a link `symlink`. |
| `content` | str | | no | The file content. Mutually exclusive with `src`. |
| `src` | path | | no | A file on the controller. |
| `link_target` | str | | no | The target of a `link`. Required for `link`. LXD returns the target as an absolute path, so the module compares that form. LXD does not set the owner or the mode of a link. |
| `owner_uid` | int | | no | The owner in the instance. Not set: keep the owner of an existing path, `0` for a new one. |
| `owner_gid` | int | | no | The group in the instance. Not set: keep the group of an existing path, `0` for a new one. |
| `mode` | str | | no | An octal string of three digits (a leading `0` is allowed). LXD drops the setuid, setgid and sticky bits, so the module refuses them. Not set: keep the mode of an existing path; a new file gets `0644`, a new directory `0755`. |

`content` is not secret by default. Use `no_log` on the task for secret content.

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST` with the content and the headers. |
| Present, same | No request. `changed: false`. |
| Content differs | `POST` with `X-LXD-write: overwrite`. |
| Only owner or mode differ | `POST` with no body and the modify-permissions header, if the server supports it. Otherwise send the content again. |
| Type differs | Fail. The module does not replace a directory with a file. |
| A directory exists with another owner or mode | Fail. LXD 6.10.1 answers the `POST` with success and changes nothing. |
| A link exists with another target | `DELETE`, then `POST`. LXD cannot replace a link. |

The module compares content by SHA-256. It reads the file with `GET` and hashes it while it streams.
For a file larger than 64 MiB, the module warns that the compare reads the whole file.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. A directory must be empty. |

## 7. Check and diff mode

The diff holds `type`, `owner_uid`, `owner_gid`, `mode`, and the SHA-256 of the content.
For a text file under 64 KiB, the diff also holds the content.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `file` | dict | `path`, `type`, `owner_uid`, `owner_gid`, `mode`, and `sha256`. `null` after a delete. |

```yaml
file:
  path: /etc/motd
  type: file
  owner_uid: 0
  owner_gid: 0
  mode: "0644"
  sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

## 9. Errors

| Case | Message |
|---|---|
| The instance is a stopped VM. | `instance <name> must run for file access` |
| `link` without `link_target`. | Ansible `required_if` error. |
| `type` differs from the server. | `<path> is a <old>, not a <new>` |
| A directory that is not empty on delete. | The LXD error. |

## 10. Cluster behavior

None. LXD sends the request to the member of the instance.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because files have no config.

| ID | Goal | Pass when |
|---|---|---|
| IF1 | `src` copies a controller file. | The SHA-256 matches. |
| IF2 | A mode change alone does not send content. | The `http_log` shows a `POST` with no body. |
| IF3 | A `directory` gets mode `0755`. | `HEAD` shows `0755`. |
| IF4 | A `link` points to its target. | `readlink` in the instance gives the target. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
