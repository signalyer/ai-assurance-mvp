"""sl gate check — query release gate decision and exit 0/1."""

from __future__ import annotations

import httpx
import typer

from .auth import sign_request
from .config import load_credentials

app = typer.Typer(help="Release gate commands.")
check_app = typer.Typer(help="Check gate decision.")
app.add_typer(check_app, name="check")


@check_app.callback(invoke_without_command=True)
def check(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID to check."),
    target: str = typer.Option("PILOT", "--target", help="Gate target environment."),
) -> None:
    """GET release gate decision for a system. Exits 0 on APPROVED/CONDITIONAL, 1 otherwise.

    Use in CI pipelines:
        sl gate check sys-payments-001 || exit 1
    """
    creds = load_credentials()
    base_url = ctx.obj.get("base_url") if ctx.obj else creds["base_url"]

    path = f"/api/grc/release-gates/v2/system/{system_id}"
    params = f"?target={target}"
    full_path = f"{path}{params}"
    headers = sign_request(
        method="GET",
        path=full_path,
        body=b"",
        api_key=creds["api_key"],
        key_id=creds["key_id"],
    )

    try:
        resp = httpx.get(f"{base_url}{full_path}", headers=headers, timeout=30)
    except httpx.RequestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if resp.status_code == 404:
        typer.echo(f"System '{system_id}' not found.", err=True)
        raise typer.Exit(code=1)

    if resp.status_code != 200:
        typer.echo(f"Server error {resp.status_code}: {resp.text}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    decision = data.get("release_decision", "UNKNOWN")
    rationale = data.get("release_rationale", "")

    typer.echo(f"System:   {system_id}")
    typer.echo(f"Decision: {decision}")
    typer.echo(f"Reason:   {rationale}")

    if decision in ("APPROVED", "CONDITIONAL"):
        raise typer.Exit(code=0)
    else:
        raise typer.Exit(code=1)
