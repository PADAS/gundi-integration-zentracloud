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


def interpret_status(status, has_device_sn):
    """Map an HTTP status to (exit_code, symbol, message).

    The tool answers one question: did the server reject the token?
    Only 401/403 mean the token is invalid. Any other response means auth
    passed, so the token works even if the specific request had other issues
    (e.g. a bad device_sn returns 4xx with a perfectly valid token).
    """
    if status == 200:
        return 0, "✓", "Token is valid and the server returned data (HTTP 200)."
    if status in (401, 403):
        return 1, "✗", (
            f"Authentication failed (HTTP {status}). "
            "The token is invalid, expired, or for a different server."
        )
    if status in (400, 422) and not has_device_sn:
        return 0, "✓", (
            f"Token accepted (HTTP {status} is the expected 'missing device_sn' response). "
            "Re-run with --device-sn <serial> for a full end-to-end check."
        )
    if status < 500:
        return 0, "✓", (
            f"Token accepted; the request returned HTTP {status} (not an auth error). "
            "This usually means a request-level issue such as an unknown device_sn."
        )
    return 0, "?", (
        f"Server error (HTTP {status}); the token was not rejected, "
        "but the result is inconclusive — try again later."
    )


def validate(token, server, device_sn=None, per_page=1, timeout=30.0, client=None):
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

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout)
    try:
        response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        print(f"✗ Could not reach the server: {exc!r}")
        return 2
    finally:
        if owns_client:
            client.close()

    code, symbol, message = interpret_status(response.status_code, has_device_sn=bool(device_sn))
    print(f"{symbol} {message}")
    if code != 0 or symbol != "✓":
        print(f"  response: {response.text[:300]}")
    return code


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
