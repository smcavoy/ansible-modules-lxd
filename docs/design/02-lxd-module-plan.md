# LXD module set plan

Status: plan for spec writers.
Audience: agents that write a spec for each module.
Read first: the Ansible module development guide (`01-ansible-module-development-guide.md`).

## 1. Goal

Build one Ansible collection that manages almost all of LXD 6.10.1 and newer.
Each module manages one LXD API resource and talks to the REST API directly.
The collection replaces the old community.general LXD modules for new work.

## 2. Sources

| Source | Version | Use |
|---|---|---|
| LXD docs and `doc/rest-api.yaml` | tag `lxd-6.10.1` | API paths, fields, config keys. |
| LXD release notes | 6.6 to 6.10.1 | Breaking changes since 6.0. |
| Terraform provider `terraform-lxd/lxd` | 3.1.1, commit of 2026-10-29 | Resource design, config merge rules, cluster patterns. |
| community.general LXD modules | 14.1.0 | Existing behavior and known gaps. |
| Test server | LXD 6.10.1 snap, `6/stable` | Checks of the real API behavior. |

LXD 6.10.0 is the first LTS release of the 6 series. The `6/stable` channel tracks it.

## 3. Current state

### 3.1 community.general

| Plugin | What it does | Gaps |
|---|---|---|
| `lxd_container` | Instances: create, config, devices, state. | One large module. Uses `trust_password`. No image registries. |
| `lxd_profile` | Profiles. | Uses `merge_profile`. Uses `trust_password`. |
| `lxd_project` | Projects. | Uses `merge_project`. Uses `trust_password`. |
| `lxd_storage_pool_info` | Reads pools. | Read only. |
| `lxd_storage_volume_info` | Reads volumes. | Read only. |
| `lxd` connection | Runs tasks in instances through the `lxc` CLI. | Not an API plugin. |
| `lxd` inventory | Builds inventory from instances. | Out of scope for this plan. |

Nothing manages networks, storage pools, volumes, images, clusters, identities, or disaster recovery.

### 3.2 Terraform provider 3.1.1

The provider has 28 resources and 12 data sources.
It is the best current model for LXD resource design.

The resources follow.

- Access: `auth_group`, `auth_identity`, `auth_identity_provider_group`, `auth_identity_token`, `trust_certificate`, `trust_token`.
- Cluster: `cluster_group`, `cluster_link`, `server`.
- Instances and images: `image`, `instance`, `instance_device`, `instance_file`, `instance_snapshot`, `profile`, `project`.
- Networks: `network`, `network_acl`, `network_forward`, `network_load_balancer`, `network_peer`, `network_zone`, `network_zone_record`.
- Storage: `storage_bucket`, `storage_bucket_key`, `storage_pool`, `storage_volume`, `storage_volume_copy`.

The provider has no resources for these items. This collection must add them:

- Cluster formation and cluster members.
- Placement groups.
- Image registries and image aliases.
- Replicators.
- Load balancer pools.
- Backups and warnings.

## 4. LXD 6.x facts that change the design

These changes came after LXD 5.21. Old modules and old examples ignore them.

| Fact | Since | Effect on modules |
|---|---|---|
| LXD removes `core.trust_password` with the patch `config_remove_core_trust_password`. | Before 6.6. The release notes do not give the release. | No `trust_password` option. Use trust tokens, bearer tokens, or certificates. |
| Bearer token authentication. | 6.7 | Support `bearer_token` in the connection options. |
| LXD removes `/1.0/containers` and `/1.0/virtual-machines`. | 6.7 | Use `/1.0/instances` only. |
| Writes to custom volumes, volume snapshots, and profiles return operations. | 6.6 | The client must wait for every operation. |
| Writes to pools, buckets, bucket keys, networks, ACLs, zones, zone records, forwards, load balancers, and peers return operations. | 6.8 | The client must wait for every operation. |
| Some writes stay synchronous. `POST /1.0/profiles` and `POST /1.0/projects` return `201`. `PUT` on a profile returns `202`. | Checked in 6.10.1 | Accept `200`, `201`, and `202` on every write. |
| LXD removes the `source` key for `ceph` and `cephfs` pools. | 6.8 | Not a computed key. Pass the server error on. |
| LXD removes the `event-hub` role. `control-plane` replaces it. | 6.8 | `lxd_cluster_member` documents the current roles only. |
| LXD removes the MAAS keys `maas.*`. | 6.8 | Do not document them. |
| Project delete is asynchronous. | 6.7 | Wait for the operation. |
| `security.csm` and `security.secureboot` became `boot.mode`. | 6.7 | Document `boot.mode` in examples. LXD 6.10.1 rejects `security.secureboot`. Alpine VMs need `boot.mode=uefi-nosecureboot`. |
| Only the `default` project can hold public images. | 6.8 | `lxd_image` fails early on `public: true` in other projects. |
| LXD removes image import from a client URL (`direct`). | 6.9 | No `url` image source. |
| Network load balancer pools with health checks. | 6.9, health checks 6.10 | `lxd_network_load_balancer_pool`. |
| Project `replica_mode` and `PUT /1.0/projects/{name}/state`. | 6.9, optional field in 6.10 | `lxd_project` manages `replica_mode`. |
| Evacuation `force` skips the raft quorum check. `mode` overrides the evacuation mode. | 6.9 | `lxd_cluster_member` takes `force` and `evacuate_mode`. |
| Image registries. Sources use `image_registry`. LXD deprecates `server` and `protocol`. | 6.10 | Instances and images name a registry. A `server` that is not a registry fails with `400` "No image registry found". |
| LXD removes cluster healing and `cluster.healing_threshold`. | 6.10 | Do not expose them. |
| LXD removes the `nvidia.*` instance keys. GPUs use CDI. | 6.10 | Do not document them. |
| `GET /1.0/state` exists for a standalone server. | 6.10 | Use it in `lxd_server_info`. |
| Identity `expires_at`, `effective_groups`, and `GET .../identities/{type}/{id}/state`. | 6.10 | `lxd_auth_info` returns them. |
| Placement groups. | 6.6 | `lxd_placement_group`. |
| Cluster links, replicators, and the `control-plane` role. | 6.8 | New modules. |
| Unidirectional and public cluster links. | 6.10 | `lxd_cluster_link` link types. |
| `GET /1.0/metadata/configuration` gives each key's scope. | Before 6.6 | Use it to split cluster-wide and member keys. |

Built-in image registries: `images`, `ubuntu`, `ubuntu-daily`, `ubuntu-minimal`, `ubuntu-minimal-daily`.
Users cannot change or delete them.

### 4.1 Findings from the test runs

The test runs on LXD 6.10.1 found these facts. The modules and the specs follow them.

| Fact | Found | Effect on the modules |
|---|---|---|
| A `PATCH` on a custom volume or a network forward without `description` sets the description to empty. | 2026-11-05 | The modules use `PUT` with the full object. |
| A `PATCH` on a network ACL merges only the config. It replaces the description and both rule lists. | 2026-11-06 | `lxd_network_acl` uses `PUT` with the full object. |
| A `PUT /1.0` changes only the keys in the body. It keeps the server keys that the body leaves out. | 2026-11-06 | `lxd_server_config` sends a removed key with an empty value. |
| Profiles, networks, pools, and ACLs replace the whole config on `PUT`. | 2026-11-06 | The modules send the full config. |
| LXD does not store a server key at its default value. | 2026-11-06 | A task that sets a key to its default reports a change on every run. The module notes say so. |
| LXD closes a new TLS connection when the handshake takes longer than 3 s. This is the `ReadHeaderTimeout` of its HTTP server. LXD does not read the request, so it does not apply a write on that connection. The client sees a reset or an EOF. This was the cause of the CI connection resets. | 2026-11-06 | The client keeps one connection per module run. It sends a write only on a connection that already gave an answer. It sends a `GET` or a `HEAD` again on a new connection, up to 3 times. It never sends a write twice. |
| LXD ends a single-file download when the client stops reading for more than 10 s. This is a `TCP_USER_TIMEOUT` on the socket. | 2026-11-06 | Only reads get this. The client sends the `GET` again. |
| A restricted identity that asks for a project outside its groups gets `Not Found`, not `Forbidden`. | 2026-11-05 | Tests check for `404`. |
| LXD lists the `pure` driver in `storage_supported_drivers` without the hardware. | 2026-11-06 | `lxd_storage_pool` cannot always fail early. LXD then fails inside the operation. |
| An `all-exclusive` snapshot names each volume snapshot after the snapshot pattern of the volume, for example `snap0`. Its description names the instance snapshot. | 2026-11-06 | `lxd_instance_snapshot` notes say so. |
| The project state returns `Limit` and `Usage` with capital letters. | 2026-11-06 | `lxd_project_info` returns them as LXD sends them. |
| A container publish gives a unified image. The image registries give split images. | 2026-11-06 | The tests export a published image to get a unified tarball. |
| An exec whose command exits with 127 or 126 fails the operation with `Command not found` or `not executable`. | 2026-11-06 | `lxd_instance_exec` returns them as `rc`. |
| A cluster member PUT keeps the automatic roles that the body leaves out. | 2026-11-06 | `lxd_cluster_member` sends only the roles that users can set. |
| LXD refuses to delete the `default` cluster group, and every member must stay in some group. | 2026-11-06 | `lxd_cluster_group` does not empty `default` before a delete. |
| An open join token or trust token is a running operation. It ends when a client uses it. | 2026-11-06 | The token modules read the token from the POST response and do not wait. |
| A cluster link create needs `type`. A pending create answers `201` with the token parts, not with an encoded token. | 2026-11-06 | `lxd_cluster_link` encodes the token as base64 of that JSON, as for a trust token. |
| A pending `unidirectional` link has no link object on the cluster that issues the token, only a pending identity. | 2026-11-06 | `lxd_cluster_link` finds the pending identity by name. `absent` revokes it. |
| A public create answers `200` with the fingerprint of the other cluster. A second `POST` with `fingerprint` confirms the link. | 2026-11-06 | `lxd_cluster_link` confirms only when the fingerprint matches. |
| A cluster holds the certificate of another cluster only once. A second link to it fails with `Certificate already exists`. | 2026-11-06 | Documented in `lxd_cluster_link`. Tests delete other links to the cluster first. |
| A delete of a link on one cluster leaves the link on the other cluster. | 2026-11-06 | Documented in `lxd_cluster_link`. |
| LXD gives neither the size nor a checksum of a backup. | 2026-11-06 | The backup modules only check that `dest` exists. |
| An instance cannot have two NICs on the same managed bridge. LXD refuses it with `Instance DNS name ... conflict`. | 2026-11-06 | The MicroCloud fixture uses a VLAN interface on the one NIC as the OVN uplink. |
| The MicroCeph, MicroOVN, and MicroCloud daemons make their certificates when the snap starts. Copies of one image then share an identity, and MicroCloud refuses the join with `Fingerprint already exists`. | 2026-11-06 | The first boot in MicroCloud mode deletes the daemon state before it starts the services. |
| The sandbox image build with the four MicroCloud snaps takes about 29 minutes. | 2026-11-06 | The bootstrap allows 45 minutes. A cached image makes later runs fast. |
| On a cluster, an OVN network needs no member-specific step. | 2026-11-06 | `lxd_network` creates an OVN network in one step on a cluster. |
| A load balancer pool gets `protocol: tcp` in its config. An instance item has only `name` when the task gives no port. The pool state is empty without health checks. | 2026-11-06 | `lxd_network_load_balancer_pool` compares a missing `target_port` as empty. |
| When one side of a mutual network peer is deleted, the other side becomes `Errored`. | 2026-11-06 | Documented in the `lxd_network_peer` findings. |
| A bucket GET returns the internal fields `ID`, `PoolID`, and `PoolName`, and the key `volatile.uuid` in its config. | 2026-11-06 | `lxd_storage_bucket` treats `volatile.*` as computed. |
| A bucket create returns the admin credentials in the operation metadata. | 2026-11-06 | `lxd_storage_bucket` returns them only on the create run. |

## 5. Collection design

### 5.1 Name and layout

Collection: `smcavoy.lxd`. Module names start with `lxd_`.
The layout is in the development guide, section 4.

### 5.2 Shared code

| File | Contents |
|---|---|
| `module_utils/_client.py` | HTTP client with one keep-alive connection, operations, errors, ETags, API extension checks. |
| `module_utils/_module.py` | `LXDModule` base class, connection argument spec, common flow. |
| `module_utils/_config.py` | Config and device compare, merge, normalize, computed keys. |
| `module_utils/_cluster.py` | Member key scopes and the pending-then-global create flow. |
| `module_utils/_typing.py` | Typing helpers, copied from community.general. |
| `doc_fragments/_connection.py` | Connection options. |
| `doc_fragments/_project.py` | The `project` option. |
| `doc_fragments/_target.py` | The `target` option for cluster members. |
| `doc_fragments/_config.py` | `config`, `config_mode`, `devices`, `devices_mode`. |
| `doc_fragments/_attributes.py` | Attributes, with `info_module` and `action_group` parts. |

### 5.3 Connection options

All modules share these options through `_connection.py` and the `lxd` action group.

| Option | Type | Environment variable | Rule |
|---|---|---|---|
| `url` | str | `LXD_URL` | `unix:` path or `https://host:port`. If not set, use the first socket that exists: `/var/snap/lxd/common/lxd/unix.socket`, then `/var/lib/lxd/unix.socket`. |
| `client_cert` | path | `LXD_CLIENT_CERT` | PEM client certificate for mutual TLS. |
| `client_key` | path | `LXD_CLIENT_KEY` | PEM client key. Required together with `client_cert`. |
| `bearer_token` | str, `no_log` | `LXD_BEARER_TOKEN` | Mutually exclusive with `client_cert`. |
| `server_cert` | path | `LXD_SERVER_CERT` | The server certificate or its CA. The client passes it as `ca_path`. |
| `validate_certs` | bool, default `true` | `LXD_VALIDATE_CERTS` | Keep `true` when the task sets `server_cert`. Then the client verifies the server with `server_cert`. |
| `trust_token` | str, `no_log` | none | Adds the client certificate to the trust store once, before the task. |
| `timeout` | int, default `120` | `LXD_TIMEOUT` | Seconds for one request and one operation wait. |

Notes:

- Without `client_cert`, the module does not read `~/.config/lxc/`. Implicit file reads give surprises on remote hosts.
- `server_cert` does not pin a fingerprint. Python also checks the host name. The certificate SAN must hold the host from `url`.
- LXD 6.10.1 puts only the host name, `127.0.0.1`, and `::1` in the SAN. It does not put the server addresses there.
- So with `server_cert`, `url` must use the server host name, not its IP address. A test confirmed an "IP address mismatch" error.
- The `server_fingerprint` option in `specs/_foundation.md` pins one certificate without the host name check.
- A module runs where the API is reachable. With `https`, that is usually `localhost`. With `unix:`, it is the LXD host.

### 5.4 Client rules

- Use `ansible.module_utils.urls.Request`. It supports Unix sockets, client certificates, and a CA path.
- Send `User-Agent: smcavoy.lxd/<version>`.
- Read `GET /1.0` once per task. Keep the API extensions and `environment.server_clustered`.
- Give each module a list of required API extensions. Fail early with the missing names.
- After a write, if the response type is `async`, wait on `/1.0/operations/<id>/wait?timeout=<n>`.
- `/wait` returns HTTP `200` also for a failed operation. Read `metadata.status`. If it is not `Success`, fail with `metadata.err`.
- Use the response `type`, `sync` or `async`, to decide whether to wait. Do not use the HTTP code.
- Read the `ETag` header from each `GET`. If present, send it as `If-Match` on `PUT`.
- LXD sends the header as `Etag`. Read headers without regard to case.
- A wrong `If-Match` gives `412` with the error "ETag does not match". A test confirmed this for profiles and networks.
- On `412`, read the object again, compute the request again, and send it once more. Then fail.
- In 6.10.1, some `PUT` handlers ignore `If-Match`. They are `/1.0/cluster`, cluster groups, instance metadata, and warnings.
- Forwards, load balancers, load balancer pools, peers, and bucket keys also ignore it.
- Their `GET` returns an `ETag`, but the server does not check it. These modules have no lost-update protection.
- Warnings return no `ETag` at all. Source: the `util.EtagCheck` calls in the LXD 6.10.1 server code. Rule R3 in `specs/README.md` holds the full list.
- Use `PUT` with the full object for updates. Do not use `PATCH`. A full object makes key removal explicit.
- Treat `404` as "not present". Treat every other error as a failure.
- Put `project` and `target` in the query string. URL-encode every path part.
- With `-vvvv`, return an `http_log` list without secrets. Never log `bearer_token`, `trust_token`, or bucket secrets.

### 5.5 Common options

| Option | Modules | Rule |
|---|---|---|
| `name` | All resource modules | The resource name. |
| `state` | All resource modules | `present` or `absent`. Instances also take `started`, `stopped`, `frozen`, `restarted`. |
| `project` | Project-scoped resources | Default: not sent. LXD then uses `default`. |
| `target` | Instances, volumes, buckets, cluster-member actions | A cluster member, or `@group` for a cluster group. Fail on a standalone server. |
| `description` | Resources with a description | A string. `None` means "do not manage". |
| `config` | Resources with config | A dictionary of string keys. See section 5.6. |
| `config_mode` | Resources with config | `merge` or `exact`. See section 5.6. |
| `devices` | Instances and profiles | A dictionary of device name to properties. |
| `devices_mode` | Instances and profiles | `merge` or `exact`. |
| `member_config` | Storage pools, networks, server | Per-member values. See section 5.8. |

### 5.6 Config handling

LXD config is a flat map of string to string. Terraform shows the safe way to manage it.

Rules:

1. Convert values to strings before compare and send. `true` becomes `"true"`. `10` becomes `"10"`.
2. Fail if a value is a list or a dictionary.
3. A value of `null` in the task means "remove this key".
4. An empty string `""` also means "unset" in LXD. Treat `""` and a missing key as equal. A `PUT` with `""` removes the key. A test confirmed this for profiles and networks.
5. Never compare or remove computed keys. Each module has a list.
6. `config_mode: merge` is the default. The module sets the keys in `config`. Other keys stay.
7. `config_mode: exact` removes every key that is not in `config`, except computed keys.
8. Put the key list in the diff, not the whole server object.

Computed keys from the Terraform provider:

| Resource | Computed keys |
|---|---|
| Instance | `volatile.*`, `image.*` |
| Network | `volatile.*`, `bridge.mtu`, `ipv4.address`, `ipv4.nat`, `ipv6.address`, `ipv6.nat` |
| Storage pool, `dir` | `source` |
| Storage pool, `zfs` | `source`, `size`, `zfs.pool_name` |
| Storage pool, `lvm` | `source`, `size`, `lvm.vg_name`, `lvm.thinpool_name` |
| Storage pool, `btrfs` | `source`, `size` |
| Storage pool, `ceph` | `ceph.cluster_name`, `ceph.user.name`, `ceph.osd.pg_num`, `ceph.osd.pool_name`, `ceph.osd.pool_size` |
| Storage pool, `cephfs` | `cephfs.cluster_name`, `cephfs.user.name`, `cephfs.osd_pg_num`, `cephfs.osd_pool_size` |
| Storage pool, `cephobject` | `cephobject.cluster_name`, `cephobject.user.name` |
| Storage pool, `alletra` | `alletra.mode` |
| Storage pool, `powerflex` | `powerflex.mode`, `powerflex.user.name` |
| Storage pool, `powerstore` | `powerstore.mode`, `powerstore.user.name` |
| Storage pool, `pure` | `pure.mode` |
| Storage pool, every driver | `volatile.*` |
| Storage volume | `volatile.*`, `block.filesystem`, `block.mount_options`, plus keys inherited from the pool's `volume.*` keys |
| Project | `features.images`, `features.profiles`, `features.storage.volumes`, `features.storage.buckets` |
| Cluster link | `volatile.*` |

If the user sets a computed key in `config`, the module manages it like any other key.
Spec writers must check each list against `GET /1.0/metadata/configuration`.
The Terraform provider lists `source` for `ceph` and `cephfs`. LXD 6.8 removed that key, so the table omits it.

### 5.7 Device handling

- `devices` is a dictionary: name to a dictionary of properties. Each entry needs `type`.
- Convert property values to strings, like config.
- A device value of `null` removes the device.
- `devices_mode: merge` keeps devices that are not in the task. `exact` removes them.
- Compare a device as a whole dictionary. Any change replaces the whole device.
- Devices that come from profiles are not instance devices. Do not compare them.

### 5.8 Cluster patterns

Some config keys are member-specific. `GET /1.0/metadata/configuration` marks them with scope `local`.

Create flow for storage pools and networks on a cluster, from the Terraform provider:

1. Split `config` into global keys and local keys, with the metadata scopes.
2. For each member, `POST` with `?target=<member>` and only that member's local keys. The resource is `Pending`.
3. `POST` once without `target`, with the global keys. The resource becomes `Created`.
4. If a step fails, report which member failed. Do not delete what exists.

Update flow: `PUT` global keys without `target`. `PUT` each member's local keys with `?target=<member>`.

Read rules on a cluster:

- `GET` without `target` omits local keys. Read each member with `?target=<member>` to get its local keys.
- A request without `target` must hold no local key. `PUT` returns `400` "Config key ... is cluster member specific".
- `POST` without `target` returns `202`. The operation then fails with the same error. Check the scopes before the request, so the error comes early.
- A global key with `target` returns `400` with the error `Config key ... may not be used as member-specific key`.
- A test confirmed the create flow for a `bridge` network and a `dir` pool on a 3-member cluster.

Local keys in LXD 6.10.1, from `lxd/metadata/configuration.json`:

| Entity | Local keys |
|---|---|
| `dir` pool | `source`, `source.recover` |
| `zfs` pool | `size`, `source`, `source.recover`, `source.wipe`, `zfs.pool_name` |
| `btrfs` pool | `size`, `source`, `source.recover`, `source.wipe` |
| `lvm` pool | `size`, `source`, `source.recover`, `source.wipe`, `lvm.vg_name`, `lvm.thinpool_name` |
| `cephobject` and `pure` pools | `size`, `source.recover` |
| `ceph`, `cephfs`, `alletra`, `powerflex`, and `powerstore` pools | `source.recover` |
| `bridge` network | `bridge.external_interfaces`, `bgp.ipv4.nexthop`, `bgp.ipv6.nexthop` |
| `macvlan`, `physical`, and `sriov` networks | `parent` |
| Server | `core.https_address`, `cluster.https_address`, `core.bgp_address`, `core.bgp_routerid`, `core.debug_address`, `core.dns_address`, `core.metrics_address`, `core.syslog_socket`, `storage.backups_volume`, `storage.images_volume`, `storage.project.<name>.backups_volume`, `storage.project.<name>.images_volume` |

The API gives the same data at `GET /1.0/metadata/configuration`.
The path is `metadata.configs.<entity>.<section>.keys`. Each item is a map with one key name. Its value holds `scope`.

`member_config` is a dictionary: member name to a dictionary of local keys.
A local key in `config` is the default for all members. `member_config` overrides it.
Fail if `member_config` holds a global key.

Return the resolved per-member config as `members` in the result.

On a standalone server, fail if the task sets `member_config`.

### 5.9 Check mode, diff mode, and results

- Every module supports check mode. Write paths send nothing in check mode.
- Every resource module supports diff mode. `before` and `after` hold only managed fields.
- Each resource module returns the resource after the change, under a key named after the resource.
  Example: `lxd_network` returns `network`.
- In check mode, return the predicted object.
- When `state: absent`, return the object as `None` and a `changed` flag.
- An info module returns a list under the plural key, for example `networks`. A missing `name` gives an empty list, not a failure.

### 5.10 Operations that are not declarative

Some API calls run an action, not a state. Examples: exec, token creation, backup export, cluster join token.
Rules for these modules:

- Name them after the result, not the verb. Example: `lxd_cluster_join_token`, not `lxd_cluster_add`.
- Document in `attributes` that check mode does not run the action.
- Return `changed: true` when the action runs.
- Offer a guard where possible, such as `creates` on `lxd_instance_exec`.
- A state that runs an action on each run, such as `restarted` or `restored`, always reports a change. Document it.

### 5.11 What is out of scope

- The `lxc` CLI. Modules never call it.
- `lxc remote` client config. It lives on the client, not in the API.
- The events websocket, console, and SFTP endpoints.
- `/1.0/metrics`, `/1.0/auth/oidc-sessions`, and `/1.0/instances/{name}/uefi-vars`.
- Changed block tracking: the `bitmaps` and `nbd` endpoints. It is a feature preview in 6.10.
- `POST /1.0/images/{fingerprint}/refresh` and `/secret`. Plan an image refresh option after version 1.
- `/1.0/instances/{name}/logs/exec-output`.
- Inventory and connection plugins. Plan these later, after the modules.
- `lxd init` before the API is reachable. Use the snap and `lxd_server_config` after that.

## 6. Module catalog

Priority: P1 first, then P2, then P3.
Cluster: "yes" means that the module needs a cluster test. See the testing framework document.

### 6.1 Foundation (no module)

| Item | Priority |
|---|---|
| `_client.py`, `_module.py`, `_config.py`, `_cluster.py` | P1 |
| Doc fragments and the `lxd` action group | P1 |
| Test framework roles and runner | P1 |

### 6.2 Server and cluster

| Module | API | State or action | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_server_config` | `GET/PUT /1.0` | Server `config`, with `member_config`. | P1 | yes | `lxd_server` |
| `lxd_server_info` | `/1.0`, `/1.0/resources`, `/1.0/state`, `/1.0/metadata/configuration` | Read. Choose parts with `gather`. | P1 | yes | `lxd_info` |
| `lxd_cluster` | `GET/PUT /1.0/cluster`, `DELETE /1.0/cluster/members/{name}` | `enabled` on the first member. `joined` with a join token. `absent` leaves. | P2 | yes | none |
| `lxd_cluster_join_token` | `POST /1.0/cluster/members` | Creates a join token for a new member name. | P2 | yes | none |
| `lxd_cluster_member` | `/1.0/cluster/members/{name}` and `POST .../state` | `roles`, `groups`, `failure_domain`, `config`, `description`. `state`: `present`, `evacuated`, `absent`. `present` restores an evacuated member. `evacuate_mode`, `restore_mode`, and `force`. | P2 | yes | none |
| `lxd_cluster_member_info` | `GET /1.0/cluster/members` | Read, with state. | P2 | yes | none |
| `lxd_cluster_group` | `/1.0/cluster/groups` | `members`, `description`. | P2 | yes | `lxd_cluster_group` |
| `lxd_cluster_certificate` | `PUT /1.0/cluster/certificate` | Replaces the cluster certificate. Compare by fingerprint. | P3 | yes | none |
| `lxd_cluster_link` | `/1.0/cluster/links` | Bidirectional, unidirectional, and public links. | P3 | yes, two clusters | `lxd_cluster_link` |
| `lxd_cluster_link_info` | `GET /1.0/cluster/links` and `/state` | Read. | P3 | yes | data source |
| `lxd_placement_group` | `/1.0/placement-groups` | LXD requires the `config` keys `policy` and `rigor`. Project-scoped. | P3 | yes | none |

### 6.3 Projects

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_project` | `/1.0/projects`, `PUT .../state` | `config`, `description`. `force_delete` for `state: absent`. `replica_mode`: `leader`, `standby`, or `""` to clear, through `PUT .../state`. | P1 | no | `lxd_project` |
| `lxd_project_info` | `GET /1.0/projects` and `/state` | Read, with usage. | P1 | no | data source |

### 6.4 Instances

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_instance` | `/1.0/instances`, `/state` | See section 7.1. | P1 | yes, for `target` | `lxd_instance` |
| `lxd_instance_info` | `GET /1.0/instances?recursion=2` | Read config, state, and addresses. Filter by name or `filter`. | P1 | no | data source |
| `lxd_instance_device` | Instance `devices` | One device on an instance that other code owns. | P2 | no | `lxd_instance_device` |
| `lxd_instance_snapshot` | `/instances/{name}/snapshots` | `present`, `absent`, `restored`. `restored` always reports a change. `stateful`, `expires_at`. | P1 | no | `lxd_instance_snapshot` |
| `lxd_instance_file` | `/instances/{name}/files` | Push `content` or `src`. Compare by checksum. `mode`, `uid`, `gid`. `state: absent` deletes. | P2 | no | `lxd_instance_file` |
| `lxd_instance_exec` | `POST /instances/{name}/exec` | Runs a command. Returns `rc`, `stdout`, `stderr`. `creates` and `removes` guards. | P2 | no | `execs` block |
| `lxd_instance_backup` | `/instances/{name}/backups` | `present`, `absent`. Optional `dest` downloads the export to the controller. | P2 | no | none |
| `lxd_instance_rebuild` | `POST /instances/{name}/rebuild` | Action module. Always reports a change. Needs `force` when the instance runs. | P3 | no | none |
| `lxd_instance_metadata` | `/instances/{name}/metadata` and templates | Manage `templates`. | P3 | no | none |
| `lxd_instance_log_info` | `/instances/{name}/logs` | Read a log file. | P3 | no | none |

### 6.5 Profiles

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_profile` | `/1.0/profiles` | `config`, `devices`, `description`. | P1 | no | `lxd_profile` |
| `lxd_profile_info` | `GET /1.0/profiles` | Read. | P1 | no | data source |

### 6.6 Images

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_image` | `/1.0/images` | See section 7.2. | P1 | no | `lxd_image` |
| `lxd_image_alias` | `/1.0/images/aliases` | `target` fingerprint, `description`, `type`. | P1 | no | `aliases` field |
| `lxd_image_info` | `GET /1.0/images` | Read by fingerprint, alias, or `filter`. | P1 | no | data source |
| `lxd_image_export` | `/images/{fp}/export` | Download to `dest_dir` on the controller. Skip if checksum matches. | P3 | no | none |
| `lxd_image_registry` | `/1.0/image-registries` | LXD infers the protocol: `config.url` gives `simplestreams`, and `config.cluster` with `config.source_project` gives `lxd`. LXD computes `public`. Built-in registries are read-only. | P1 | no | none |
| `lxd_image_registry_info` | `GET /1.0/image-registries` and `/images` | Read registries and the images they offer. | P2 | no | none |

### 6.7 Storage

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_storage_pool` | `/1.0/storage-pools` | `driver`, `config`, `member_config`. Pending-then-global on a cluster. | P1 | yes | `lxd_storage_pool` |
| `lxd_storage_pool_info` | `GET /1.0/storage-pools` and `/resources` | Read, with usage. | P1 | no | data source |
| `lxd_storage_volume` | `/storage-pools/{p}/volumes/custom` | `content_type`, `config`. Sources: empty, copy, snapshot, ISO upload, tarball. | P1 | yes, for `target` | `lxd_storage_volume`, `lxd_storage_volume_copy` |
| `lxd_storage_volume_info` | `GET /1.0/storage-volumes` and pool volumes | Read across pools or in one pool. | P1 | no | none |
| `lxd_storage_volume_snapshot` | `/volumes/{type}/{name}/snapshots` | `present`, `absent`, `restored`. `restored` always reports a change. | P2 | no | none |
| `lxd_storage_volume_backup` | `/volumes/{type}/{name}/backups` | `present`, `absent`, optional `dest`. | P3 | no | none |
| `lxd_storage_bucket` | `/storage-pools/{p}/buckets` | Needs a `cephobject` pool. LXD 6.8 removes local MinIO buckets. | P3 | yes, Ceph | `lxd_storage_bucket` |
| `lxd_storage_bucket_key` | `/buckets/{b}/keys` | `role`. Returns the secret once, with `no_log`. | P3 | yes, Ceph | `lxd_storage_bucket_key` |

### 6.8 Networking

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_network` | `/1.0/networks` | Types `bridge`, `macvlan`, `sriov`, `ovn`, `physical`. `member_config`. | P1 | yes | `lxd_network` |
| `lxd_network_info` | `GET /1.0/networks`, `/state`, `/leases` | Read, with state and DHCP leases. | P1 | no | data source |
| `lxd_network_acl` | `/1.0/network-acls` | `ingress` and `egress` rule lists. Compare as sets. | P1 | no | `lxd_network_acl` |
| `lxd_network_acl_info` | `GET /1.0/network-acls` and `/log` | Read. | P2 | no | data source |
| `lxd_network_zone` | `/1.0/network-zones` | `config` with `dns.nameservers`, `peers.*`. | P2 | no | `lxd_network_zone` |
| `lxd_network_zone_record` | `/network-zones/{z}/records` | `entries` list of type, value, TTL. Compare as a set. | P2 | no | `lxd_network_zone_record` |
| `lxd_network_forward` | `/networks/{n}/forwards` | Key is `listen_address`. `ports` list. | P2 | no | `lxd_network_forward` |
| `lxd_network_load_balancer` | `/networks/{n}/load-balancers` | Needs OVN. `backends`, `ports`. | P3 | yes, OVN | `lxd_network_load_balancer` |
| `lxd_network_load_balancer_pool` | `/networks/{n}/load-balancer-pools` and `/state` | Needs OVN and LXD 6.9. `instances`, health check config. | P3 | yes, OVN | none |
| `lxd_network_peer` | `/networks/{n}/peers` | Needs OVN. Local and mutual peers. | P3 | yes, OVN | `lxd_network_peer` |
| `lxd_network_allocation_info` | `GET /1.0/network-allocations` | Read used addresses. | P3 | no | none |

### 6.9 Access control

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_auth_group` | `/1.0/auth/groups` | `permissions` list of entity type, URL, entitlement. Compare as a set. | P1 | no | `lxd_auth_group` |
| `lxd_auth_identity` | `/1.0/auth/identities/{tls,bearer,oidc}` | `type`, `groups`. TLS from a certificate or a pending token. | P1 | no | `lxd_auth_identity` |
| `lxd_auth_identity_token` | `POST .../bearer/{id}/token` | Issues a bearer token. Action module. `no_log` result. | P2 | no | `lxd_auth_identity_token` |
| `lxd_auth_identity_provider_group` | `/1.0/auth/identity-provider-groups` | Map IdP groups to LXD groups. | P2 | no | `lxd_auth_identity_provider_group` |
| `lxd_auth_info` | Identities, groups, `/current`, `/permissions` | Read. Include effective groups. | P2 | no | data sources |
| `lxd_trust_certificate` | `/1.0/certificates` | Legacy trust store. Keep for `restricted` certificates. | P2 | no | `lxd_trust_certificate` |
| `lxd_trust_token` | `POST /1.0/certificates` with `token: true` | Action module. Returns the token. | P2 | no | `lxd_trust_token` |

### 6.10 Disaster recovery

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_replicator` | `/1.0/replicators` | `config.cluster`, `config.schedule`. `state`: `present`, `absent`. | P3 | yes, two clusters | none |
| `lxd_replicator_run` | `PUT /replicators/{n}/state` | Action module. `mode`: `start` or `restore`. Always reports a change. | P3 | yes, two clusters | none |
| `lxd_replicator_info` | `GET /1.0/replicators` and `/state` | Read last run and status. | P3 | yes | none |

### 6.11 Operations and warnings

| Module | API | Notes | Priority | Cluster | Terraform |
|---|---|---|---|---|---|
| `lxd_operation_info` | `GET /1.0/operations` | Read running operations. | P3 | no | none |
| `lxd_warning` | `/1.0/warnings/{uuid}` | `status`: `new` or `acknowledged`. `state: absent` deletes. | P3 | no | none |
| `lxd_warning_info` | `GET /1.0/warnings` | Read, with filters. | P3 | no | none |

Count: 63 modules. 22 are P1.

## 7. Notes for the large modules

### 7.1 `lxd_instance`

Options:

| Option | Rule |
|---|---|
| `name`, `project`, `target` | Standard. The module uses `target` only on create. |
| `type` | `container` or `virtual-machine`. Cannot change after create. If it differs, warn and continue, per rule R10 in `specs/README.md`. |
| `source` | Dictionary. Keys: `image` (alias or fingerprint), `image_registry`, `instance` (copy), `snapshot`, `empty: true`. The module uses it only on create. |
| `profiles` | List. Order matters. `null` means "do not manage". `[]` means no profiles. |
| `config`, `config_mode` | Section 5.6. |
| `devices`, `devices_mode` | Section 5.7. |
| `ephemeral`, `description` | Standard. |
| `state` | `present`, `started`, `stopped`, `frozen`, `restarted`, `absent`. |
| `force` | Force stop and force delete. LXD 6.7 added forced delete through the API. `DELETE ?force=true` stops and deletes a running instance in one call. Without it, LXD returns `400` with the error `Instance is running`. |
| `wait_for` | List of conditions: `agent`, `ipv4`, `ipv6`, `ready`, `delay`. Like Terraform. |
| `allow_restart` | If a config change needs a restart, restart the instance. Otherwise fail with a clear message. |
| `stop_timeout` | Seconds before a clean stop becomes a failure. |

Rules:

- `restarted` always reports a change. Document it.
- A config change on a running VM can need a restart. Read the LXD error. Do not guess.
- Return `instance` with `state.network` addresses after `wait_for`.
- Do not expose `nvidia.*` keys or `security.csm`.

### 7.2 `lxd_image`

Sources, used only when the image is not present:

| Source | Fields |
|---|---|
| Registry | `image_registry`, `alias` or `fingerprint`, `image_type`. |
| Instance publish | `instance`, optional `snapshot`, `compression_algorithm`. |
| Upload | `path` to a unified tarball, or `metadata_path` and `rootfs_path`. |

Identity: the module finds the image by `fingerprint`, or by the first alias in `aliases`.
Managed fields: `aliases`, `properties`, `public`, `auto_update`, `profiles`, `expires_at`.
Only the `default` project accepts `public: true`.

Upload a split image as `multipart/form-data` with the parts `metadata` and `rootfs`.
Send `X-LXD-public` and `X-LXD-properties` as headers. The operation metadata gives the fingerprint.
A test confirmed this on 6.10.1.

## 8. Spec template

Each spec is one Markdown file, `specs/<module>.md`. It contains these sections:

1. **Purpose.** One sentence.
2. **API.** Each path and method, and the required API extensions.
3. **Identity.** Which fields find the resource.
4. **Options.** A table: name, type, default, required, rule. Mark create-only options.
5. **Computed keys.** The list for this resource.
6. **Behavior per state.** For each state: absent case, present case, change case.
7. **Check and diff mode.** What the diff holds.
8. **Return values.** Keys and a sample.
9. **Errors.** Each expected failure and its message.
10. **Cluster behavior.** `target`, `member_config`, or "none".
11. **Tests.** The integration cases from the testing framework, plus module-specific cases.
12. **Hardware exceptions.** Parts that the test server cannot test.
13. **Open questions.**

## 9. Delivery order

1. Foundation: shared code, fragments, action group, test runner.
2. P1 standalone: `lxd_project`, `lxd_profile`, `lxd_network`, `lxd_network_acl`, `lxd_storage_pool`, `lxd_storage_volume`, `lxd_image_registry`, `lxd_image`, `lxd_image_alias`, `lxd_instance`, `lxd_instance_snapshot`, `lxd_server_config`, `lxd_auth_group`, `lxd_auth_identity`, and their `_info` modules.
3. Cluster fixture, then the cluster parts of P1 modules.
4. P2 modules.
5. OVN fixture, then the OVN modules.
6. Ceph fixture, then buckets.
7. Two-cluster fixture, then cluster links and replicators.
8. P3 modules, with `lxd_cluster_certificate`.

Each phase ends when the full LXD suite passes: `ci/run-lxd.sh --all`.
