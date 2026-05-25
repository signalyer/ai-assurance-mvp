"""Generate role-based demo creds + bcrypt hashes + session secret.

Idempotent: if deploy/creds.txt AND deploy/appsettings.json already exist, exits
without regenerating (preserves stakeholders' working passwords across redeploys).
Pass --rotate to force regeneration.

To ADD missing roles to an existing creds.txt WITHOUT rotating the existing
passwords (Session 44+ V2-PORTAL-SPLIT prep — append ENGINEER without
disrupting stakeholders), use deploy/add-missing-creds.py instead.

Outputs:
- deploy/creds.txt        (plaintext, for handing to stakeholders — NEVER COMMIT)
- deploy/appsettings.json (settings to push via `az webapp config appsettings set`)

Session 44: ROLES extended to include OPERATOR (S11 Demo Control gap-fill) and
ENGINEER (V2-PORTAL-SPLIT A6 — engineer → Team Workspace landing).
"""

import argparse
import json
import secrets
import string
import sys
from pathlib import Path

import bcrypt

# Must stay in sync with middleware/auth.py ROLES. Order is intentional —
# CRO/CISO/AUDIT/MRM/AIGOV are governance roles (CISO Console landing per S43
# A7); OPERATOR/ENGINEER are workspace roles (Team Workspace landing per A6).
ROLES = ["CRO", "CISO", "AUDIT", "MRM", "AIGOV", "OPERATOR", "ENGINEER"]
ALPHABET = string.ascii_letters + string.digits + "!@#$%^*-_=+"


def gen_password(n: int = 16) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="Force regeneration even if creds exist")
    args = ap.parse_args()

    out_dir = Path(__file__).resolve().parent
    creds_file = out_dir / "creds.txt"
    settings_file = out_dir / "appsettings.json"

    if creds_file.exists() and settings_file.exists() and not args.rotate:
        print(f"PRESERVING existing creds at {creds_file} (use --rotate to regenerate)")
        return

    creds: list[tuple[str, str, str]] = []  # (username, password, hash)

    for role in ROLES:
        username = f"demo-{role.lower()}"
        password = gen_password()
        bhash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        creds.append((username, password, bhash))

    session_secret = secrets.token_urlsafe(48)

    # creds.txt — plaintext for the operator to share
    with (out_dir / "creds.txt").open("w", encoding="utf-8") as fh:
        fh.write("AI ASSURANCE PLATFORM — DEMO CREDENTIALS\n")
        fh.write("=" * 56 + "\n\n")
        fh.write(f"{'USERNAME':<20}  {'PASSWORD'}\n")
        fh.write(f"{'-'*20:<20}  {'-'*20}\n")
        for u, p, _ in creds:
            fh.write(f"{u:<20}  {p}\n")
        fh.write("\n(Bcrypt hashes are stored as App Settings — plaintext exists only in this file.)\n")

    # appsettings.json — array form accepted by `az webapp config appsettings set --settings @file`
    settings = [
        {"name": "AUTH_ENABLED", "value": "true", "slotSetting": False},
        {"name": "SESSION_SECRET", "value": session_secret, "slotSetting": False},
    ]
    for (u, _, h), role in zip(creds, ROLES):
        settings.append({"name": f"DEMO_USER_{role}_HASH", "value": h, "slotSetting": False})

    with (out_dir / "appsettings.json").open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)

    print(f"Wrote {out_dir / 'creds.txt'}")
    print(f"Wrote {out_dir / 'appsettings.json'}")
    print()
    print("Credentials (also saved to deploy/creds.txt):")
    for u, p, _ in creds:
        print(f"  {u:<20}  {p}")


if __name__ == "__main__":
    main()
