# lxd_network_zone_record

## 1. Purpose

Create, update, and delete DNS records in an LXD network zone.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/network-zones/{zone}/records/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/network-zones/{zone}/records` | `POST` | async | Create. |
| `/1.0/network-zones/{zone}/records/{name}` | `PUT` | async, checks `If-Match` | Update. |
| `/1.0/network-zones/{zone}/records/{name}` | `DELETE` | async | Delete. |

Required API extensions: `network_dns_records`.

## 3. Identity

`zone`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `zone` | str | | yes | The zone name. |
| `name` | str | | yes | The record name inside the zone, for example `www`. |
| `project` | str | | no | The project of the zone. |
| `state` | str | `present` | no | `present` or `absent`. |
| `description` | str | | no | `null` means "do not manage". |
| `entries` | list of dict | | no | Each item has `type`, `value`, and `ttl`. `null` means "do not manage". |
| `config` | dict | | no | Rule R4. Only `user.*` keys. |
| `config_mode` | str | `merge` | no | Rule R4. |

Entry fields: `type` is a DNS type such as `A`, `AAAA`, `CNAME`, or `TXT`. `ttl` is an integer, default `0`, which means the zone default.

## 5. Computed keys

None.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../records` with `name`, `description`, `entries`, and `config`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with the full object. |

The module compares `entries` as a set of `type`, `value`, and `ttl`.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description`, `entries` sorted by `type` and `value`, and `config`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `record` | dict | The record from `GET`, after the change. `null` after a delete. |

```yaml
record:
  name: www
  description: Web front end
  entries:
    - type: A
      value: 192.0.2.10
      ttl: 300
  config: {}
```

## 9. Errors

| Case | Message |
|---|---|
| The zone does not exist. | `Network zone <zone> not found` |
| An entry without `type` or `value`. | `entry <n> needs type and value` |

## 10. Cluster behavior

None.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C12. C6 to C8 use `user.*` keys.

| ID | Goal | Pass when |
|---|---|---|
| ZR1 | The same entries in another order make no change. | `changed` is false. |
| ZR2 | The record resolves through the LXD DNS server. | `dig` returns the value. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
