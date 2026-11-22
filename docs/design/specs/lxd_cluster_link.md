# lxd_cluster_link

## 1. Purpose

Create, update, and delete links between two LXD clusters, of type bidirectional, unidirectional, or public.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/cluster/links/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/cluster/links` | `POST` | sync | Create. The body decides the mode. See section 6. |
| `/1.0/cluster/links/{name}` | `PUT` | sync, checks `If-Match` | Update `description` and `config`. |
| `/1.0/cluster/links/{name}` | `DELETE` | sync | Delete. |

Required API extensions: `cluster_links`. `unidirectional` needs `cluster_links_unidirectional`. `public` needs `cluster_links_public`.

## 3. Identity

`name`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The link name on this cluster. |
| `state` | str | `present` | no | `present` or `absent`. |
| `type` | str | `bidirectional` | no | Create-only. `bidirectional`, `unidirectional`, or `public`. |
| `trust_token` | str | | no | Secret. Create-only. The token from the other cluster. |
| `auth_groups` | list | | no | Create-only. Groups for the identity of the other cluster. Not for `public`. |
| `remote_address` | str | | no | Create-only, `public` only. The address of the other cluster. |
| `fingerprint` | str | | no | Create-only, `public` only. The expected certificate fingerprint of the other cluster. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Only `user.*` keys. |
| `config_mode` | str | `merge` | no | Rule R4. |

## 5. Computed keys

`volatile.*`.

## 6. Behavior per state

### `present`, `bidirectional` and `unidirectional`

A link needs two steps, one on each cluster.

| Case | Action |
|---|---|
| Absent, no `trust_token` | `POST` with `name` and `type`. LXD makes a pending link and returns a token. The module returns it as `trust_token`. |
| Absent, with `trust_token` | `POST` with `name`, `type`, `trust_token`, and `auth_groups`. LXD contacts the other cluster and activates both sides. |
| Present | Compare `description` and `config`. `PUT` if they differ. Create-only options follow rule R10. |

Run the module without a token on cluster B. Then run it with the returned token on cluster A.

### `present`, `public`

| Case | Action |
|---|---|
| Absent | `POST` with `name`, `type: public`, and `remote_address`. LXD returns the remote fingerprint. |
| The returned fingerprint equals `fingerprint` | `POST` with `name`, `type: public`, and `fingerprint`. LXD confirms the link. |
| The fingerprints differ, or `fingerprint` is not set | Stop. Return the fingerprint. The link stays pending. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `type`, `description`, and `config`. Check mode does not contact the other cluster.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `link` | dict | The link from `GET`, after the change. `null` after a delete. |
| `trust_token` | str | Only from a pending create. Secret. Rule R9. |
| `remote_fingerprint` | str | Only from a pending `public` create. |

```yaml
link:
  name: dr-site
  type: bidirectional
  description: ""
  config:
    volatile.addresses: 10.0.0.41:8443
  used_by: []
trust_token: eyJjbGllbnRfbmFtZSI6...
```

## 9. Errors

| Case | Message |
|---|---|
| A bad token. | The LXD error `Invalid trust token: ...` |
| `trust_token` with `type: public`. | The LXD error `Trust token cannot be set for public cluster links` |
| `remote_address` without `type: public`. | The LXD error `Remote address can only be set for public cluster links` |
| Delete a link in use. | The LXD error `Cluster link is currently in use` |
| The public fingerprint differs. | `remote fingerprint <got> does not match <expected>` |

## 10. Cluster behavior

This module runs against one member of each cluster. LXD handles the other members.

## 11. Tests

Fixture: `lxd/multicluster`. Standard cases C1 to C12 on the pending side. C6 to C8 use `user.*` keys. CK1 to CK4.

| ID | Goal | Pass when |
|---|---|---|
| CK1 | A pending link on B, then an active link on A with the token. | `lxd_cluster_link_info` shows both sides with a member status. |
| CK2 | A `unidirectional` link. | The link exists with `type: unidirectional`. |
| CK3 | A `public` link with the right fingerprint. | The link is confirmed. |
| CK4 | A `public` link with a wrong fingerprint stops. | `msg` holds `does not match`. |

## 12. Hardware exceptions

None. The `multicluster` fixture builds both clusters.

## 13. Open questions

1. None. The probe in `fixture_multicluster` answered the first open question.

## 14. Findings from the tests

1. The create body needs `type`. Without it, LXD answers `Invalid cluster link type ""`.
2. A pending create answers `201` with `client_name`, `fingerprint`, `addresses`, `secret`, `expires_at`, and `type`. The token is base64 of this JSON object.
3. The pending token expires after 15 days in the test run.
4. An activation with the token answers `201` without metadata. Both links then have `volatile.addresses`. The link on the activating side also has `volatile.uuid`.
5. A pending `unidirectional` link has no link object on the cluster that issues the token. Only the identity `Cluster link certificate (pending)` exists.
6. A public create answers `200` with the fingerprint of the other cluster. The link then has `volatile.pending_address` and `volatile.pending_certificate`.
   A second `POST` with `name`, `type: public`, and `fingerprint` confirms it. The confirmed link has `volatile.addresses`.
7. A cluster holds the certificate of another cluster only once. A second link to the same cluster fails with `Certificate already exists`.
8. A delete of a link on one cluster leaves the link on the other cluster.
9. A `PATCH` of `config` keeps the description and the `volatile.*` keys. The module uses `PUT` with an ETag, as for other objects.
