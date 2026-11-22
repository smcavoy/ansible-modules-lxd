# lxd_cluster_certificate

## 1. Purpose

Replace the TLS certificate and key that all members of a cluster use.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0` | `GET` | sync | Read `environment.certificate_fingerprint`. |
| `/1.0/cluster/certificate` | `PUT` | sync | Replace the certificate and key. |

Required API extensions: `clustering_update_cert`.

## 3. Identity

Not applicable. There is one cluster certificate.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `certificate` | str | | yes | The PEM certificate. |
| `key` | str | | yes | Secret. The PEM private key, PKCS#1 or PKCS#8. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

| Case | Action |
|---|---|
| The SHA-256 fingerprint of `certificate` equals the server fingerprint | No request. `changed: false`. |
| It differs | `PUT /1.0/cluster/certificate` with `cluster_certificate` and `cluster_certificate_key`. |

After the change, clients that pin the old certificate fail. A task with `server_cert` must use the new one.

## 7. Check and diff mode

The diff holds the old and the new fingerprint. Check mode sends no request.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `fingerprint` | str | The fingerprint after the change. |
| `previous_fingerprint` | str | The fingerprint before the change. |

```yaml
fingerprint: 7b88...
previous_fingerprint: fdc8...
```

## 9. Errors

| Case | Message |
|---|---|
| A bad certificate. | The LXD error `Certificate must be PEM-encoded X.509 certificate` |
| A bad key. | The LXD error `Private key must be PEM-encoded (PKCS#1/PKCS#8) key` |
| The key does not match the certificate. | `key does not match certificate` |

## 10. Cluster behavior

LXD sends the new certificate to every member.

## 11. Tests

Fixture: `lxd/cluster`. It runs CC1 to CC3.

| ID | Goal | Pass when |
|---|---|---|
| CC1 | A new certificate replaces the old one. | `GET /1.0` shows the new fingerprint on all members. |
| CC2 | A second run makes no change. | `changed` is false. |
| CC3 | A key that does not match fails before the request. | `msg` holds `does not match`. |

The test makes a self-signed certificate with `community.crypto`, or with Python in the runner.

## 12. Hardware exceptions

None.

## 13. Open questions

1. Can a standalone server use this endpoint? The handler does not check for a cluster. Test it in the first run.
