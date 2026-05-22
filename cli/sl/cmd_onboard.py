"""sl onboard — register a new AI system via the platform intake API."""

from __future__ import annotations

import json
import webbrowser

import httpx
import typer

from .auth import sign_request
from .config import load_credentials

app = typer.Typer(help="Onboard a new AI system to the platform.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def onboard(
    ctx: typer.Context,
    system_name: str = typer.Argument(..., help="Display name for the new AI system."),
    domain: str = typer.Option("unknown", "--domain", help="Business domain (e.g. payments, credit)."),
    business_owner: str = typer.Option("(unset)", "--business-owner", help="Business owner name."),
    technical_owner: str = typer.Option("(unset)", "--technical-owner", help="Technical owner name."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip opening the portal URL in a browser."),
) -> None:
    """Submit a minimal intake form to register a new AI system.

    On success, prints the portal URL for the newly created system.
    Optionally opens the portal URL in the default browser.

    ASCII onboarding flow:

        sl onboard "Payments Agent"
            |
            v
        POST /api/grc/intake/submit
            |
            v
        Platform creates AISystem + Assessment + ReleaseGates
            |
            v
        Prints: portal URL -> /ai-systems?id=<system_id>
            |
            v
        (optional) Opens URL in browser
    """
    creds = load_credentials()
    base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

    payload_dict = {
        "name": system_name,
        "domain": domain,
        "business_owner": business_owner,
        "technical_owner": technical_owner,
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    path = "/api/grc/intake/submit"
    headers = sign_request(
        method="POST",
        path=path,
        body=body_bytes,
        api_key=creds["api_key"],
        key_id=creds["key_id"],
    )
    headers["Content-Type"] = "application/json"

    typer.echo(f"Onboarding system: {system_name!r} ...")
    try:
        resp = httpx.post(
            f"{base_url}{path}",
            content=body_bytes,
            headers=headers,
            timeout=30,
        )
    except httpx.RequestError as exc:
        typer.echo(f"Error: network request failed — {exc}", err=True)
        raise typer.Exit(code=1)

    if resp.status_code not in (200, 201):
        typer.echo(f"Error: server returned {resp.status_code} — {resp.text}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    system_id = data.get("ai_system_id", "unknown")
    redirect = data.get("redirect_to", f"/ai-systems?id={system_id}")
    portal_url = f"{base_url}{redirect}"

    typer.echo(f"System created: {system_id}")
    typer.echo(f"Portal URL:     {portal_url}")

    if not no_browser:
        webbrowser.open(portal_url)
