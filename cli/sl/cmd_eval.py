"""sl eval run — trigger an evaluation run and stream progress."""

from __future__ import annotations

import json

import httpx
import typer

from .auth import sign_request
from .config import load_credentials

app = typer.Typer(help="Evaluation commands.")
run_app = typer.Typer(help="Run an evaluation.")
app.add_typer(run_app, name="run")


@run_app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID to evaluate."),
    target: str = typer.Option("PILOT", "--target", help="Evaluation target environment (PILOT or PRODUCTION)."),
) -> None:
    """POST /api/grc/release-gates/v2/system/<system_id> and exit 0 on PASS, 1 on FAIL.

    Prints gate evaluation results line by line.
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

    typer.echo(f"Running evaluation for {system_id} (target={target}) ...")
    try:
        resp = httpx.get(f"{base_url}{full_path}", headers=headers, timeout=60)
    except httpx.RequestError as exc:
        typer.echo(f"Error: network request failed — {exc}", err=True)
        raise typer.Exit(code=1)

    if resp.status_code == 404:
        typer.echo(f"Error: system '{system_id}' not found.", err=True)
        raise typer.Exit(code=1)

    if resp.status_code != 200:
        typer.echo(f"Error: server returned {resp.status_code} — {resp.text}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    decision = data.get("release_decision", "UNKNOWN")
    rationale = data.get("release_rationale", "")
    pass_count = data.get("pass_count", 0)
    fail_count = data.get("fail_count", 0)
    blocking = data.get("blocking_failures", [])

    typer.echo(f"\nDecision:  {decision}")
    typer.echo(f"Rationale: {rationale}")
    typer.echo(f"Passed:    {pass_count}  Failed: {fail_count}")

    if blocking:
        typer.echo("\nBlocking failures:")
        for bf in blocking:
            typer.echo(f"  - {bf}")

    gates = data.get("gates", [])
    if gates:
        typer.echo("\nGate results:")
        for g in gates:
            status = g.get("status", "UNKNOWN")
            name = g.get("gate_name", g.get("name", "unknown"))
            typer.echo(f"  [{status:10}] {name}")

    if decision in ("APPROVED", "CONDITIONAL"):
        raise typer.Exit(code=0)
    else:
        raise typer.Exit(code=1)
