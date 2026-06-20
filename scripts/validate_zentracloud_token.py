#!/usr/bin/env python3
"""Validate a ZentraCloud token against a chosen server.

Mirrors exactly what the pull_observations action sends (normalized
``Authorization: Token <token>`` header and the same server URLs), so a pass
here means the integration's credentials will work in production.

Examples:
    python scripts/validate_zentracloud_token.py --token "5a99..." --server tahmo
    python scripts/validate_zentracloud_token.py --token "Token 5a99..." \\
        --server tahmo --device-sn z6-27505

Run from the repo root (so ``app`` is importable). Exit code 0 = token works.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

# Allow running as `python scripts/validate_zentracloud_token.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.actions.configurations import AuthenticateConfig, ZentraCloudServer


SERVER_CHOICES = {s.name.lower(): s for s in ZentraCloudServer}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", required=True, help="ZentraCloud account token (with or without the 'Token ' prefix).")
    parser.add_argument(
        "--server",
        choices=sorted(SERVER_CHOICES),
        default="us",
        help="ZentraCloud server hosting the devices (default: us).",
    )
    parser.add_argument("--device-sn", help="Optional device serial number for a fuller end-to-end check.")
    parser.add_argument("--per-page", type=int, default=1, help="Readings per page for the test request (default: 1).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30).")
    return parser.parse_args(argv)


def validate(token, server, device_sn=None, per_page=1, timeout=30.0):
    config = AuthenticateConfig(token=token, api_url=SERVER_CHOICES[server])
    url = config.api_url
    headers = {"Authorization": config.auth_header}

    params = {
        "per_page": per_page,
        "start_date": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
    }
    if device_sn:
        params["device_sn"] = device_sn

    print(f"→ GET {url}")
    print(f"  server={server}  device_sn={device_sn or '(none)'}")

    try:
        response = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        print(f"✗ Could not reach the server: {exc!r}")
        return 2

    status = response.status_code
    if status == 200:
        print("✓ Token is valid and the server returned data (HTTP 200).")
        return 0
    if status in (401, 403):
        print(f"✗ Authentication failed (HTTP {status}). The token is invalid, expired, or for a different server.")
        print(f"  response: {response.text[:300]}")
        return 1
    if status in (400, 422) and not device_sn:
        print(f"✓ Token accepted (HTTP {status} is the expected 'missing device_sn' response).")
        print("  Re-run with --device-sn <serial> for a full end-to-end check.")
        return 0
    print(f"? Unexpected response (HTTP {status}). Token likely accepted; inspect the body:")
    print(f"  response: {response.text[:300]}")
    return 0 if status < 400 else 1


def main(argv=None):
    args = parse_args(argv)
    return validate(
        token=args.token,
        server=args.server,
        device_sn=args.device_sn,
        per_page=args.per_page,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
