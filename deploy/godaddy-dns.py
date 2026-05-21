"""Set GoDaddy DNS records via API.

Usage:
    python godaddy-dns.py upsert --domain sandboxhub.co --type CNAME --name aigovern --data app-aigovern-dev.azurewebsites.net
    python godaddy-dns.py upsert --domain sandboxhub.co --type TXT   --name asuid.aigovern --data <verification-id>
    python godaddy-dns.py wait   --fqdn aigovern.sandboxhub.co --expect app-aigovern-dev.azurewebsites.net

Reads GODADDY_API_KEY and GODADDY_API_SECRET from environment (or from .env in repo root).
Never logs the key/secret.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v.strip())


def _creds() -> tuple[str, str]:
    key = os.environ.get("GODADDY_API_KEY", "").strip()
    sec = os.environ.get("GODADDY_API_SECRET", "").strip()
    if not key or not sec:
        sys.exit("ERROR: GODADDY_API_KEY and GODADDY_API_SECRET required (set in .env)")
    return key, sec


def _request(method: str, url: str, body: list | dict | None = None) -> tuple[int, str]:
    key, sec = _creds()
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"sso-key {key}:{sec}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


def upsert_record(domain: str, rtype: str, name: str, data: str, ttl: int = 600) -> None:
    """Replace (PUT) the record set for {type}/{name} at {domain}."""
    rtype = rtype.upper()
    url = f"https://api.godaddy.com/v1/domains/{domain}/records/{rtype}/{name}"
    body = [{"data": data, "ttl": ttl}]
    code, text = _request("PUT", url, body)
    if 200 <= code < 300:
        print(f"OK  {rtype:5} {name}.{domain} -> {data}")
        return
    sys.exit(f"FAIL ({code}) {rtype} {name}.{domain}: {text[:300]}")


def wait_dns(fqdn: str, expect: str, timeout_s: int = 600) -> None:
    """Block until `fqdn` resolves to the same IP set as `expect` (or timeout)."""
    deadline = time.time() + timeout_s
    expected_ips: set[str] = set()
    try:
        expected_ips = {ai[4][0] for ai in socket.getaddrinfo(expect, None)}
    except socket.gaierror:
        pass
    last_seen: set[str] = set()
    while time.time() < deadline:
        try:
            seen = {ai[4][0] for ai in socket.getaddrinfo(fqdn, None)}
        except socket.gaierror:
            seen = set()
        if seen and (not expected_ips or seen & expected_ips):
            print(f"OK  {fqdn} resolves to {sorted(seen)}")
            return
        if seen != last_seen and seen:
            print(f"... {fqdn} -> {sorted(seen)} (waiting for overlap with {sorted(expected_ips) or 'expected'})")
            last_seen = seen
        time.sleep(20)
    sys.exit(f"TIMEOUT waiting for {fqdn} to resolve (saw: {sorted(last_seen)})")


def main() -> None:
    load_env()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("upsert")
    u.add_argument("--domain", required=True)
    u.add_argument("--type", required=True)
    u.add_argument("--name", required=True)
    u.add_argument("--data", required=True)
    u.add_argument("--ttl", type=int, default=600)

    w = sub.add_parser("wait")
    w.add_argument("--fqdn", required=True)
    w.add_argument("--expect", required=True)
    w.add_argument("--timeout", type=int, default=600)

    args = p.parse_args()
    if args.cmd == "upsert":
        upsert_record(args.domain, args.type, args.name, args.data, args.ttl)
    elif args.cmd == "wait":
        wait_dns(args.fqdn, args.expect, args.timeout)


if __name__ == "__main__":
    main()
