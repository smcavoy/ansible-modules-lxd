# Foundation: shared code, fragments, action group, test roles

## 1. Purpose

Give every module one client, one base class, one config engine, and one cluster helper, with tests.

## 2. API

| Path | Method | Use |
|---|---|---|
| `/1.0` | `GET` | Server info, API extensions, `auth`, `environment.server_clustered`, `environment.server_name`. |
| `/1.0/operations/{id}/wait` | `GET` | Wait for an async operation. |
| `/1.0/metadata/configuration` | `GET` | Config key scopes for `_cluster.py`. |
| `/1.0/certificates` | `POST` | Add the client certificate with `trust_token`. Needs `explicit_trust_token`. |
| `/1.0/cluster/members` | `GET` | Member names for `member_config` and `target` checks. |

Required API extensions: none for the foundation. Each module lists its own.

## 3. Identity

Not applicable.

## 4. Options

The connection options in section 5.3 of the module plan, in `doc_fragments/_connection.py`.

| Fragment | Options |
|---|---|
| `_connection` | `url`, `client_cert`, `client_key`, `bearer_token`, `server_cert`, `server_fingerprint`, `validate_certs`, `trust_token`, `timeout` |
| `_project` | `project` |
| `_target` | `target` |
| `_config` | `config`, `config_mode`, `devices`, `devices_mode` |
| `_attributes` | `check_mode`, `diff_mode`, `platform`, and the parts `info_module` and `action_group` |

`meta/runtime.yml` holds `requires_ansible: '>=2.19.0'` and the action group `lxd` with every module.

## 5. Computed keys

`_config.py` holds the computed key lists from section 5.6 of the module plan.
It keeps them as glob patterns, for example `volatile.*`. Each module passes its resource name.

## 6. Behavior

### 6.1 `_client.py`

| Part | Rule |
|---|---|
| Transport | `ansible.module_utils.urls.Request`. A `unix:` URL uses `unix_socket` and the base `http://unix.socket`. |
| Default URL | The first socket that exists: `/var/snap/lxd/common/lxd/unix.socket`, then `/var/lib/lxd/unix.socket`. |
| TLS | `client_cert` and `client_key` go to `Request`. `server_cert` goes to `ca_path`. `server_fingerprint` pins one certificate by its SHA-256, without the chain and host name checks, as `lxc` does. It is for joined cluster members. |
| Bearer token | Header `Authorization: Bearer <token>`. |
| Headers | `User-Agent: smcavoy.lxd/<version>`. `Content-Type: application/json` for JSON bodies. |
| Server info | `GET /1.0` once per task. Keep `api_extensions`, `auth`, and `environment`. |
| Trust token | If `auth` is `untrusted` and `trust_token` is set, `POST /1.0/certificates` with `type: client` and `trust_token`. Then read `/1.0` again. |
| Untrusted | If `auth` is still `untrusted`, fail with `The LXD server does not trust this client`. |
| Requests | Rule R2. Return the decoded `metadata` and the `ETag` header. |
| ETags | Rule R3. One retry on `412`. |
| Raw bodies | Upload and download of bytes for files, images, and backups. Stream to and from disk in blocks. |
| Errors | Raise `LXDClientError` with the HTTP code, the LXD error text, and the operation ID if there is one. |
| Log | Keep a list of method, path, query, status, and time per request. Never keep bodies, tokens, or keys. |

### 6.2 `_module.py`

| Part | Rule |
|---|---|
| Base class | `LXDModule` wraps `AnsibleModule`. It adds the connection argument spec. |
| Extensions | `require_extensions(names)` fails with the missing names. |
| Project | Sends `project` only when the task sets it. |
| Target | Fails on a standalone server. On a cluster, fails if the member or group does not exist. |
| Result | `exit(changed, key, value, diff)` adds `diff` in diff mode and `http_log` at verbosity 4 or more. |
| Check mode | Writes go through `write()`. In check mode, `write()` records the request and sends nothing. |

### 6.3 `_config.py`

| Function | Rule |
|---|---|
| `normalize(config)` | Converts values to strings. Booleans become `true` and `false`. Fails on a list or a dictionary. |
| `merge(current, desired, mode, computed)` | Returns the new config and the changed keys. Rule R4. |
| `merge_devices(current, desired, mode)` | Returns the new devices and the changed names. Rule R5. |
| `diff(before, after, keys)` | Returns `before` and `after` with only the given keys. |

### 6.4 `_cluster.py`

| Function | Rule |
|---|---|
| `key_scopes(client, entity)` | Reads `/1.0/metadata/configuration` once. Returns the set of `local` keys for the entity. |
| `split(config, local_keys)` | Returns the global keys and the local keys. |
| `create_pending_then_global(...)` | Runs the create flow from section 5.8 of the module plan. Reports the member that fails. |
| `read_members(...)` | Reads each member with `?target=<member>`. Returns the local keys per member. |

Entity names for `key_scopes` are the `configs` keys, for example `storage-zfs` and `network-bridge`.

## 7. Check and diff mode

The base class handles both modes. A module never sends a write directly.

## 8. Return values

| Key | When | Rule |
|---|---|---|
| `http_log` | Verbosity 4 or more | A list of requests without secrets. |
| `diff` | Diff mode | `before` and `after` of the managed fields. |

## 9. Errors

The shared errors in section 4 of the README, plus these:

| Case | Message |
|---|---|
| No socket and no `url`. | `No LXD socket found. Set url.` |
| `client_cert` without `client_key`. | Ansible `required_together` error. |
| The client is not trusted. | `The LXD server does not trust this client` |
| The server is older than 6.10.1. | `LXD server version <v> is older than 6.10.1` |

## 10. Cluster behavior

`_cluster.py` holds all cluster logic. Modules call it. They do not read key scopes themselves.

## 11. Tests

Unit tests in `tests/unit/plugins/module_utils/`:

| Test | Goal |
|---|---|
| `test_client_async` | An async write waits and returns the operation result. |
| `test_client_failed_operation` | A `/wait` with `status: Failure` and HTTP `200` raises an error with `err`. |
| `test_client_412_retry` | A `412` reads the object again and sends once more. A second `412` fails. |
| `test_client_unix_socket` | A `unix:` URL uses the socket and the base `http://unix.socket`. |
| `test_client_no_secrets_in_log` | The log holds no token, key, or body. |
| `test_config_normalize` | Numbers and booleans become strings. A list fails. |
| `test_config_merge_modes` | `merge` keeps unmanaged keys. `exact` removes them and keeps computed keys. |
| `test_config_null_and_empty` | `null` removes a key. `""` and a missing key are equal. |
| `test_devices_merge` | A changed property replaces the whole device. |
| `test_cluster_split` | Local and global keys split by scope. |
| `test_cluster_pending_flow` | The create sends one `POST` per member, then one `POST` without `target`. |

Integration roles in `tests/integration/targets/`:

| Role | Goal |
|---|---|
| `setup_lxd_connection` | Sets `module_defaults` for `group/smcavoy.lxd.lxd` from `integration_config.yml`. |
| `setup_lxd_project` | Creates `t-<run>-<target>` with `features.profiles` and `features.storage.volumes` on. |
| `setup_lxd_images` | Uploads the pinned test images with `ansible.builtin.uri`. |
| `setup_lxd_cluster` | Fixture role for the runner. It never uses the collection modules. |

The runner `tests/lxd/lxdtest` follows sections 5 to 11 of the testing framework.

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `_client.py` cache `/1.0/metadata/configuration` on disk between tasks? This spec says no.
