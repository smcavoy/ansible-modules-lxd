# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Send one S3 request with AWS signature version 4, and print the HTTP status.

Usage: s3_request.py METHOD URL [BODY]. The keys come from S3_ACCESS_KEY and S3_SECRET_KEY, so they stay out of the logs.
The tests use it because the runner has no S3 client.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REGION = "us-east-1"


def sign(key: bytes, text: str) -> bytes:
    """Return the HMAC-SHA256 of a text."""
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def main() -> int:
    """Send the request and print the status."""
    method, url = sys.argv[1], sys.argv[2]
    body = sys.argv[3].encode() if len(sys.argv) > 3 else b""
    access, secret = os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"]
    parts = urllib.parse.urlsplit(url)
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    payload = hashlib.sha256(body).hexdigest()
    headers = {"host": parts.netloc, "x-amz-content-sha256": payload, "x-amz-date": stamp}
    signed = ";".join(sorted(headers))
    canonical = "\n".join(
        [method, urllib.parse.quote(parts.path or "/"), parts.query, "".join(f"{name}:{headers[name]}\n" for name in sorted(headers)), signed, payload]
    )
    scope = f"{day}/{REGION}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = sign(sign(sign(sign(("AWS4" + secret).encode(), day), REGION), "s3"), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed}, Signature={signature}"
    request = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            print(response.status)
    except urllib.error.HTTPError as exc:
        print(exc.code)
        return 0
    if method == "GET":
        sys.stdout.write(content.decode(errors="replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
