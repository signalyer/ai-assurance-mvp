"""Append missing role creds to existing deploy/creds.txt + appsettings.json
WITHOUT rotating existing passwords.

Use this when middleware/auth.py ROLES grows (Session 44: ENGINEER added for
V2-PORTAL-SPLIT A6; OPERATOR back-filled from S11). Stakeholders' existing
demo-cro / demo-ciso / etc. passwords remain unchanged; only the NEW roles
get generated + appended.

Workflow:
    1. python deploy/add-missing-creds.py
       → appends any role from middleware.auth.ROLES that lacks a
         DEMO_USER_<ROLE>_HASH entry in deploy/appsettings.json
    2. az webapp config appsettings set --name app-aigovern-dev \\
         --resource-group rg-aigovern-dev \\
         --settings @deploy/appsettings.json
       → pushes the new role hash; existing settings are no-ops (same values)

Exit codes:
    0 — succeeded (either appended new roles or confirmed nothing missing)
    1 — pre-conditions failed (no existing creds.txt — run generate-creds.py first)
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
from pathlib import Path

import bcrypt

# Add the project root to sys.path so `from middleware.auth import ROLES`
# resolves regardless of CWD (the script may be run from repo root or from
# deploy/). Project root is the parent of this file's directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Single source of truth for the canonical role list.
from middleware.auth import ROLES as AUTH_ROLES  # type: ignore[import]  # noqa: E402

ALPHABET = string.ascii_letters + string.digits + "!@#$%^*-_=+"


def gen_password(n: int = 16) -> str:
    """Generate a 16-char URL-safe-ish demo password."""
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def existing_role_hashes(settings: list[dict]) -> set[str]:
    """Return the set of roles already represented in appsettings.json."""
    out: set[str] = set()
    for entry in settings:
        name = entry.get("name", "")
        if name.startswith("DEMO_USER_") and name.endswith("_HASH"):
            role = name[len("DEMO_USER_") : -len("_HASH")]
            out.add(role)
    return out


def main() -> int:
    """Append missing creds; preserve existing.

    Returns the process exit code (0 success, 1 missing prereqs).
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which roles would be appended without modifying files.",
    )
    args = ap.parse_args()

    deploy_dir = Path(__file__).resolve().parent
    creds_file = deploy_dir / "creds.txt"
    settings_file = deploy_dir / "appsettings.json"

    if not creds_file.exists() or not settings_file.exists():
        print(
            "ERROR: deploy/creds.txt and deploy/appsettings.json must already exist. "
            "Run `python deploy/generate-creds.py` first to bootstrap the initial credentials.",
            file=sys.stderr,
        )
        return 1

    with settings_file.open("r", encoding="utf-8") as fh:
        settings: list[dict] = json.load(fh)

    have = existing_role_hashes(settings)
    want = set(AUTH_ROLES)
    missing = sorted(want - have)

    if not missing:
        print(f"All {len(want)} roles already provisioned: {sorted(have)}")
        return 0

    print(f"Missing roles to append: {missing}")
    if args.dry_run:
        print("--dry-run set; no files modified.")
        return 0

    appended: list[tuple[str, str]] = []  # (username, password) for stdout summary
    for role in missing:
        username = f"demo-{role.lower()}"
        password = gen_password()
        bhash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        settings.append(
            {"name": f"DEMO_USER_{role}_HASH", "value": bhash, "slotSetting": False}
        )
        appended.append((username, password))

    # Rewrite appsettings.json with the appended entries.
    with settings_file.open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)

    # Append plaintext creds to the human-readable file. We APPEND rather than
    # rewrite to preserve the original "DEMO CREDENTIALS" header + existing
    # rows verbatim. Stakeholders' working passwords are never touched.
    with creds_file.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write(f"-- Appended by add-missing-creds.py ({len(appended)} new role(s)) --\n")
        for u, p in appended:
            fh.write(f"{u:<20}  {p}\n")

    print(f"Appended {len(appended)} role(s) to {settings_file.name} + {creds_file.name}:")
    for u, p in appended:
        print(f"  {u:<20}  {p}")
    print()
    print("Next step: push to Azure App Service:")
    print(
        "  az webapp config appsettings set --name app-aigovern-dev "
        "--resource-group rg-aigovern-dev --settings @deploy/appsettings.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
