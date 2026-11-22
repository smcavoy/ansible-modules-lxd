<!--
Copyright (c) 2026, Sean McAvoy
GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
SPDX-License-Identifier: GPL-3.0-or-later
-->

# smcavoy.lxd

Ansible modules for [LXD](https://canonical.com/lxd) 6.10.1 or newer. The modules talk to the LXD REST API directly.
They need no Python library outside `ansible-core`.

Status: early development. The interfaces can change before version 1.0.0.

## Install

```sh
ansible-galaxy collection install smcavoy.lxd
```

Or from this repository: `ansible-galaxy collection install git+https://github.com/smcavoy/ansible-modules-lxd.git`

Report a defect or ask for a feature in the [issues](https://github.com/smcavoy/ansible-modules-lxd/issues) on GitHub.
`CONTRIBUTING.md` explains how to send a change. `SECURITY.md` explains how to report a security problem.

## Modules

| Module | Purpose |
|---|---|
| `lxd_server_config` | Server config keys, with member-specific keys on a cluster. |
| `lxd_cluster_member` | Cluster member roles, groups, failure domain, and config. Evacuate and restore. |
| `lxd_cluster` | Form a cluster, join a server with a token, or remove a member. |
| `lxd_cluster_group` | Cluster groups and their members. |
| `lxd_cluster_certificate` | The certificate and key of a cluster, compared by fingerprint. |
| `lxd_placement_group` | Placement groups that spread instances over members or keep them together. |
| `lxd_cluster_link` | Links between two clusters: pending, active, unidirectional, and public. |
| `lxd_cluster_join_token` | Join tokens for new cluster members. |
| `lxd_project` | Projects, with config, description, and replica mode. |
| `lxd_replicator` | Replicators that copy a project to another cluster over a cluster link. |
| `lxd_replicator_run` | A replicator run now, forward or as a restore. |
| `lxd_profile` | Profiles, with config and devices. |
| `lxd_network` | Networks, with member-specific keys on a cluster. |
| `lxd_network_acl` | Network ACLs with ingress and egress rules. |
| `lxd_network_forward` | Network forwards from a listen address to instances. |
| `lxd_network_peer` | Peers between OVN networks. |
| `lxd_network_load_balancer` | OVN load balancers with backends and port rules. |
| `lxd_network_load_balancer_pool` | Pools of instances for OVN load balancers, with health checks. |
| `lxd_network_zone` | DNS zones for networks. |
| `lxd_network_zone_record` | Records in DNS zones. |
| `lxd_storage_pool` | Storage pools for all drivers, with member-specific keys on a cluster. |
| `lxd_storage_volume` | Custom storage volumes, empty, copied, or imported. |
| `lxd_storage_volume_snapshot` | Snapshots of custom volumes: create, expire, restore, and delete. |
| `lxd_storage_volume_backup` | Backups of custom volumes: create, download, and delete. |
| `lxd_storage_bucket` | S3 buckets on a `cephobject` pool. Admin credentials once, on create. |
| `lxd_storage_bucket_key` | Access keys of buckets, with fixed or generated secrets. |
| `lxd_image` | Images from a registry, an instance, a file, or another project, with properties and aliases. |
| `lxd_image_alias` | Image aliases, apart from their images. |
| `lxd_image_export` | Image files downloaded to the controller, checked against the fingerprint. |
| `lxd_image_registry` | Image registries that instances and images use as sources. |
| `lxd_instance` | Containers and virtual machines, and their run state. |
| `lxd_instance_device` | One device of an instance that other code owns. |
| `lxd_instance_rebuild` | A fresh root disk for an instance, from an image or empty. |
| `lxd_instance_metadata` | The properties and templates in the `metadata.yaml` of an instance. |
| `lxd_instance_snapshot` | Instance snapshots: create, expire, restore, and delete. |
| `lxd_instance_backup` | Instance backups on the server, with a download. |
| `lxd_instance_file` | Files, directories, and symlinks in instances. |
| `lxd_instance_exec` | Commands in instances, with their output. |
| `lxd_auth_group` | Authorization groups and their permissions. |
| `lxd_auth_identity` | TLS, bearer, and OIDC identities and their groups. |
| `lxd_auth_identity_token` | Tokens of bearer identities. |
| `lxd_auth_identity_provider_group` | Mappings from identity provider groups to LXD groups. |
| `lxd_trust_certificate` | Certificates in the legacy trust store. |
| `lxd_trust_token` | Trust tokens for new clients. |
| `lxd_warning` | Warnings: acknowledge, reset, and delete. |

Read-only info modules: `lxd_server_info`, `lxd_cluster_member_info`, `lxd_project_info`, `lxd_profile_info`, `lxd_network_info`,
`lxd_network_acl_info`, `lxd_storage_pool_info`, `lxd_storage_volume_info`, `lxd_image_info`, `lxd_image_registry_info`,
`lxd_instance_info`, `lxd_auth_info`, `lxd_cluster_link_info`, `lxd_replicator_info`,
`lxd_network_allocation_info`, `lxd_operation_info`, `lxd_warning_info`, and `lxd_instance_log_info`.

The design documents in `docs/design/` describe the full set of 63 planned modules.

## Connection

Every module takes the same connection options. Set them once with `module_defaults`:

```yaml
- hosts: localhost
  module_defaults:
    group/smcavoy.lxd.lxd:
      url: https://lxd.example.net:8443
      client_cert: ~/.config/lxc/client.crt
      client_key: ~/.config/lxc/client.key
      server_cert: ~/.config/lxc/servercerts/lxd.crt
  tasks:
    - name: Create a project
      smcavoy.lxd.lxd_project:
        name: web
```

Without `url`, a module uses the local LXD socket.

`server_cert` checks the certificate and the host name.
To trust exactly one certificate by its SHA-256 fingerprint instead, as `lxc` does, set `server_fingerprint`.
Use it for a server that you reach by its IP address, or for a joined cluster member, which presents the cluster certificate.

## Tests

| Command | What it runs |
|---|---|
| `ci/run-fast.sh` | Lint, docs, licenses, build, sanity, and unit tests. |
| `ci/run-lxd.sh` | Integration targets and scenarios on a test LXD server, through its API. |
| `ci/run-smoke.sh` | A small set of scenarios for pull requests. |
| `tests/lxd/lxdtest run` | The runner itself, inside the runner container on the test server. |
| `python3 ci/bootstrap.py` | Sets up a test project. The LXD CI jobs run it first. With `--check`, it only shows the state and the plan. |

The scenarios in `tests/scenarios/` use many modules together, as a user does.
To run one integration target by hand against your own test server, copy `tests/integration/integration_config.yml.template` to
`tests/integration/integration_config.yml` and set the values. The template explains each variable; the runner writes the same file for each slot.
`docs/design/03-lxd-testing-framework.md` describes the test framework. The fast checks run in GitHub Actions on each pull request.
The integration suite needs an LXD server; the maintainer runs it on a test server before a release.

## License

GNU General Public License v3.0 or later. See `COPYING`.
