# Module specs for the LXD collection

Status: draft for review.
Audience: agents that write the modules and their tests.
Read first: the development guide, the module plan, and the testing framework.

## 1. How to use these specs

Each module has one spec, `specs/<module>.md`. Each spec follows the template in section 8 of the module plan.
Rules that many modules share are in section 3 of this file. A spec names them by ID, for example "rule R3".
A spec states only what is special for its module. If a spec and this file differ, the spec wins.

The facts come from the LXD `6.10.1` source: `shared/api`, `lxd/*.go`, `doc/rest-api.yaml`, and `lxd/metadata/configuration.json`.
A test confirmed the client behavior in rule R2.

## 2. Spec index

| Group | Spec | Priority |
|---|---|---|
| Foundation | `_foundation.md` | P1 |
| Server and cluster | `lxd_server_config.md`, `lxd_server_info.md` | P1 |
| Server and cluster | `lxd_cluster.md`, `lxd_cluster_join_token.md`, `lxd_cluster_member.md`, `lxd_cluster_member_info.md`, `lxd_cluster_group.md` | P2 |
| Server and cluster | `lxd_cluster_certificate.md`, `lxd_cluster_link.md`, `lxd_cluster_link_info.md`, `lxd_placement_group.md` | P3 |
| Projects | `lxd_project.md`, `lxd_project_info.md` | P1 |
| Instances | `lxd_instance.md`, `lxd_instance_info.md`, `lxd_instance_snapshot.md` | P1 |
| Instances | `lxd_instance_device.md`, `lxd_instance_file.md`, `lxd_instance_exec.md`, `lxd_instance_backup.md` | P2 |
| Instances | `lxd_instance_rebuild.md`, `lxd_instance_metadata.md`, `lxd_instance_log_info.md` | P3 |
| Profiles | `lxd_profile.md`, `lxd_profile_info.md` | P1 |
| Images | `lxd_image.md`, `lxd_image_alias.md`, `lxd_image_info.md`, `lxd_image_registry.md` | P1 |
| Images | `lxd_image_registry_info.md` | P2 |
| Images | `lxd_image_export.md` | P3 |
| Storage | `lxd_storage_pool.md`, `lxd_storage_pool_info.md`, `lxd_storage_volume.md`, `lxd_storage_volume_info.md` | P1 |
| Storage | `lxd_storage_volume_snapshot.md` | P2 |
| Storage | `lxd_storage_volume_backup.md`, `lxd_storage_bucket.md`, `lxd_storage_bucket_key.md` | P3 |
| Networking | `lxd_network.md`, `lxd_network_info.md`, `lxd_network_acl.md` | P1 |
| Networking | `lxd_network_acl_info.md`, `lxd_network_zone.md`, `lxd_network_zone_record.md`, `lxd_network_forward.md` | P2 |
| Networking | `lxd_network_load_balancer.md`, `lxd_network_load_balancer_pool.md`, `lxd_network_peer.md`, `lxd_network_allocation_info.md` | P3 |
| Access control | `lxd_auth_group.md`, `lxd_auth_identity.md` | P1 |
| Access control | `lxd_auth_identity_token.md`, `lxd_auth_identity_provider_group.md`, `lxd_auth_info.md`, `lxd_trust_certificate.md`, `lxd_trust_token.md` | P2 |
| Disaster recovery | `lxd_replicator.md`, `lxd_replicator_run.md`, `lxd_replicator_info.md` | P3 |
| Operations and warnings | `lxd_operation_info.md`, `lxd_warning.md`, `lxd_warning_info.md` | P3 |

Count: 63 module specs and 1 foundation spec.

## 3. Shared rules

### R1. Connection

Every module takes the connection options from section 5.3 of the module plan, through the `lxd` action group.
The spec does not list them again.

### R2. Requests and operations

1. Accept `200`, `201`, and `202` on a write. Use the response `type`, not the HTTP code.
2. If `type` is `async`, wait on `GET /1.0/operations/<id>/wait?timeout=<n>`.
3. `/wait` returns HTTP `200` for a failed operation too. Read `metadata.status`. If it is not `Success`, fail with `metadata.err`.
4. If the wait returns while the operation still runs, wait again until the `timeout` option ends. Then fail with the operation ID.
5. Treat `404` on `GET` as "not present". Treat every other error as a failure. Put the LXD error text in `msg`.
6. Put `project` and `target` in the query string. URL-encode every path part.

### R3. ETags

Read the `ETag` header from each `GET`. LXD sends it as `Etag`, so read headers without regard to case.
Send it as `If-Match` on `PUT`. On `412`, read the object again, compute the request again, and send it once more. Then fail.

In 6.10.1, some `PUT` handlers do not call `util.EtagCheck`. Those modules have no lost-update protection:

| Endpoint | Module |
|---|---|
| `PUT /1.0/cluster` | `lxd_cluster` |
| `PUT /1.0/cluster/groups/{name}` | `lxd_cluster_group` |
| `PUT /1.0/instances/{name}/metadata` | `lxd_instance_metadata` |
| `PUT /1.0/networks/{n}/forwards/{address}` | `lxd_network_forward` |
| `PUT /1.0/networks/{n}/load-balancers/{address}` | `lxd_network_load_balancer` |
| `PUT /1.0/networks/{n}/load-balancer-pools/{name}` | `lxd_network_load_balancer_pool` |
| `PUT /1.0/networks/{n}/peers/{name}` | `lxd_network_peer` |
| `PUT /1.0/storage-pools/{p}/buckets/{b}/keys/{k}` | `lxd_storage_bucket_key` |
| `PUT /1.0/warnings/{uuid}` | `lxd_warning` |

Send `If-Match` to these endpoints anyway. A later LXD release can add the check.

### R4. Config

Use the rules in section 5.6 of the module plan for `config` and `config_mode`.

- `config` is a dictionary. The module converts each value to a string. A list or a dictionary value fails.
- A `null` value removes the key. An empty string and a missing key are equal.
- `config_mode: merge` is the default. `exact` removes every key that is not in `config`, except computed keys.
- `config: null` means "do not manage config". The module then sends the current config back unchanged.

### R5. Devices

Use the rules in section 5.7 of the module plan for `devices` and `devices_mode`.
Each device is a dictionary with `type`. The module compares a device as a whole.

### R6. Cluster members

Use the rules in section 5.8 of the module plan for `target` and `member_config`.

- `target` on a standalone server fails with `target is only valid on a clustered server`.
- `member_config` on a standalone server fails with `member_config is only valid on a clustered server`.
- `_cluster.py` reads the key scopes from `GET /1.0/metadata/configuration` once per task.

### R7. Check mode, diff mode, and results

Use the rules in section 5.9 of the module plan.

- In check mode, the module sends no write request. It returns the predicted object.
- The diff holds only managed fields. `before` is `{}` on create. `after` is `{}` on delete.
- A resource module returns the object under its singular key, for example `network`. After a delete, the key is `null`.
- An info module returns a list under its plural key. A missing name gives an empty list.

### R8. Actions

Use the rules in section 5.10 of the module plan for modules that run an action.
These modules support check mode, but they do not run the action in check mode. They report `changed: true`.

### R9. Secrets

Mark every option that holds a secret with `no_log: true`.
Document a secret return value as a secret. It appears only on the run that makes it.
The `http_log` never holds a request body or a response body for these endpoints.

### R10. Create-only options

A create-only option can differ on an existing resource. Then the module warns and continues.
The warning names the option and says that it applies only on create.
The module does not change the resource for that option. It applies all other options.
The rule covers every create-only option, also `type`, `driver`, `content_type`, and a peer target.

## 4. Shared errors

Every module can fail with these messages. A spec lists only the extra ones.

| Case | Message |
|---|---|
| The server lacks an API extension. | `LXD server lacks the API extensions: <names>` |
| `target` on a standalone server. | `target is only valid on a clustered server` |
| A config value is a list or a dictionary. | `config value for <key> must be a string, a number, or a boolean` |
| The project does not exist. | `Project not found: <project>` |
| A restricted client asks for another project. | The LXD error, for example `Certificate is restricted` |
| An operation fails. | `LXD operation <id> failed: <err>` |
| A wait ends after `timeout`. | `LXD operation <id> did not finish in <n> seconds` |

## 5. Shared tests

Resource modules run the standard cases C1 to C12 from section 9 of the testing framework.
Info modules run I1 to I4. Each spec names the cases that it skips and the extra cases that it adds.
Each target uses the fixture alias that its spec names in section 11.

## 6. Corrections to the module plan

The source showed these differences from the module plan. The specs follow the source.

1. `lxd_image_registry` has no `protocol` or `public` option. LXD infers the protocol from `config.url` or `config.cluster`. It computes `public` from the cluster link type.
2. The protocol of a registry cannot change after create. The update path validates the new config against the old protocol.
3. The list of `PUT` handlers without an ETag check is longer than the plan says. Rule R3 holds the full list.
4. `lxd_cluster_group` `PUT` ignores `If-Match`, but its `PATCH` checks it. The module uses `PUT` for a full update.

The module plan holds the fixes for items 1 and 3.

## 7. Corrections from the test runs

Section 4.1 of the module plan lists the facts that the test runs found on LXD 6.10.1.
These specs have a section 14 with their facts:
`lxd_server_config`, `lxd_network_acl`, `lxd_instance_snapshot`, `lxd_project_info`, `lxd_storage_pool`,
`lxd_image`, `lxd_storage_volume`, `lxd_network_forward`, and `lxd_auth_identity`.
