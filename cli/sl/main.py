"""SignalLayer CLI — root command and subcommand dispatch."""

from __future__ import annotations

import typer

from . import __version__
from .config import DEFAULT_BASE_URL

app = typer.Typer(
    name="sl",
    help="SignalLayer AI Assurance CLI — govern, evaluate, and release AI systems.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# Subcommand groups that have nested sub-commands
gate_app = typer.Typer(help="Release gate commands.")
app.add_typer(gate_app, name="gate")

eval_app = typer.Typer(help="Evaluation commands.")
app.add_typer(eval_app, name="eval")

trace_app = typer.Typer(help="Trace streaming commands.")
app.add_typer(trace_app, name="trace")

evidence_app = typer.Typer(help="Evidence commands.")
app.add_typer(evidence_app, name="evidence")


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"sl version {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Print version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    base_url: str = typer.Option(
        DEFAULT_BASE_URL,
        "--base-url",
        envvar="SL_BASE_URL",
        help="Override the platform base URL for this invocation.",
    ),
) -> None:
    """SignalLayer CLI.

    Set SL_BASE_URL or use --base-url to point at a non-production instance.
    """
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url


# ---------------------------------------------------------------------------
# sl login
# ---------------------------------------------------------------------------

@app.command("login")
def login(
    ctx: typer.Context,
    api_key: str = typer.Option(..., "--api-key", help="HMAC API key (keep secret)."),
    base_url_opt: str = typer.Option(DEFAULT_BASE_URL, "--base-url", help="Platform base URL."),
    key_id: str = typer.Option("cli-key", "--key-id", help="Key identifier sent in X-SL-Key-Id header."),
) -> None:
    """Store HMAC credentials locally so subsequent commands authenticate automatically.

    Credentials are written to ~/.signallayer/credentials.json with mode 0600 (POSIX).
    On Windows the file is created but NTFS ACLs must be tightened manually via icacls.
    """
    from .config import save_credentials
    path = save_credentials(api_key=api_key, base_url=base_url_opt, key_id=key_id)
    typer.echo(f"Credentials saved to {path}")
    typer.echo(
        "File permissions: 0600 (POSIX) — on Windows run: "
        f'icacls "{path}" /inheritance:r /grant:r "%USERNAME%:(R,W)"'
    )


# ---------------------------------------------------------------------------
# sl onboard
# ---------------------------------------------------------------------------

@app.command("onboard")
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
    import json
    import webbrowser
    import httpx
    from .auth import sign_request
    from .config import load_credentials

    creds = load_credentials()
    eff_base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

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
        resp = httpx.post(f"{eff_base_url}{path}", content=body_bytes, headers=headers, timeout=30)
    except httpx.RequestError as exc:
        typer.echo(f"Error: network request failed — {exc}", err=True)
        raise typer.Exit(code=1)

    if resp.status_code not in (200, 201):
        typer.echo(f"Error: server returned {resp.status_code} — {resp.text}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    system_id = data.get("ai_system_id", "unknown")
    redirect = data.get("redirect_to", f"/ai-systems?id={system_id}")
    portal_url = f"{eff_base_url}{redirect}"

    typer.echo(f"System created: {system_id}")
    typer.echo(f"Portal URL:     {portal_url}")

    if not no_browser:
        webbrowser.open(portal_url)


# ---------------------------------------------------------------------------
# sl eval run
# ---------------------------------------------------------------------------

@eval_app.command("run")
def eval_run(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID to evaluate."),
    target: str = typer.Option("PILOT", "--target", help="Evaluation target environment."),
) -> None:
    """POST gate evaluation and exit 0 on PASS (APPROVED/CONDITIONAL), 1 on FAIL."""
    import httpx
    from .auth import sign_request
    from .config import load_credentials

    creds = load_credentials()
    eff_base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

    path = f"/api/grc/release-gates/v2/system/{system_id}"
    full_path = f"{path}?target={target}"
    headers = sign_request(method="GET", path=full_path, body=b"",
                           api_key=creds["api_key"], key_id=creds["key_id"])

    typer.echo(f"Running evaluation for {system_id} (target={target}) ...")
    try:
        resp = httpx.get(f"{eff_base_url}{full_path}", headers=headers, timeout=60)
    except httpx.RequestError as exc:
        typer.echo(f"Error: {exc}", err=True)
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
    typer.echo(f"\nDecision:  {decision}")
    typer.echo(f"Rationale: {rationale}")
    typer.echo(f"Passed:    {data.get('pass_count', 0)}  Failed: {data.get('fail_count', 0)}")

    if decision in ("APPROVED", "CONDITIONAL"):
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# sl gate check
# ---------------------------------------------------------------------------

@gate_app.command("check")
def gate_check(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID to check."),
    target: str = typer.Option("PILOT", "--target", help="Gate target environment."),
) -> None:
    """GET release gate decision. Exits 0 on APPROVED/CONDITIONAL, 1 otherwise."""
    import httpx
    from .auth import sign_request
    from .config import load_credentials

    creds = load_credentials()
    eff_base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

    full_path = f"/api/grc/release-gates/v2/system/{system_id}?target={target}"
    headers = sign_request(method="GET", path=full_path, body=b"",
                           api_key=creds["api_key"], key_id=creds["key_id"])

    try:
        resp = httpx.get(f"{eff_base_url}{full_path}", headers=headers, timeout=30)
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
    typer.echo(f"System:   {system_id}")
    typer.echo(f"Decision: {decision}")
    typer.echo(f"Reason:   {data.get('release_rationale', '')}")

    if decision in ("APPROVED", "CONDITIONAL"):
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# sl trace tail
# ---------------------------------------------------------------------------

@trace_app.command("tail")
def trace_tail(
    ctx: typer.Context,
    system: str = typer.Option("", "--system", help="Filter to a specific system ID (optional)."),
    limit: int = typer.Option(50, "--limit", help="Maximum number of events to print."),
) -> None:
    """Connect to the platform traces endpoint and print events. Press Ctrl+C to stop."""
    import json
    import httpx
    from .auth import sign_request
    from .config import load_credentials

    creds = load_credentials()
    eff_base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

    path = "/api/traces"
    headers = sign_request(method="GET", path=path, body=b"",
                           api_key=creds["api_key"], key_id=creds["key_id"])

    typer.echo("Tailing traces (Ctrl+C to stop) ...")
    seen_ids: set[str] = set()
    count = 0

    try:
        with httpx.stream("GET", f"{eff_base_url}{path}", headers=headers, timeout=30) as resp:
            if resp.status_code != 200:
                typer.echo(f"Error: server returned {resp.status_code}", err=True)
                raise typer.Exit(code=1)
            raw = resp.read()
            parsed = json.loads(raw)
            for trace in parsed.get("traces", []):
                tid = trace.get("id", "")
                if tid in seen_ids:
                    continue
                if system and trace.get("system_id", "") != system:
                    continue
                seen_ids.add(tid)
                ts = trace.get("timestamp", "")
                model = trace.get("model", "")
                preview = trace.get("prompt_preview", "")[:80]
                typer.echo(f"[{ts}] model={model} | {preview}")
                count += 1
                if count >= limit:
                    break
    except httpx.RequestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        pass

    typer.echo(f"Done — {count} event(s) shown.")


# ---------------------------------------------------------------------------
# sl evidence export
# ---------------------------------------------------------------------------

@evidence_app.command("export")
def evidence_export(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID."),
    framework: str = typer.Option(..., "--framework", help="Framework slug (e.g. eu_ai_act)."),
    out: str = typer.Option(".", "--out", help="Output file path (.zip) or directory."),
) -> None:
    """Download a ZIP evidence package for a system/framework combination."""
    import json
    import zipfile
    from pathlib import Path
    import httpx
    from .auth import sign_request
    from .config import load_credentials

    creds = load_credentials()
    eff_base_url = (ctx.obj or {}).get("base_url") or creds["base_url"]

    out_path = Path(out)
    if out_path.is_dir():
        out_file = out_path / f"{system_id}_{framework}_evidence.zip"
    else:
        out_file = out_path

    path = f"/api/frameworks/{framework}/system/{system_id}"
    headers = sign_request(method="GET", path=path, body=b"",
                           api_key=creds["api_key"], key_id=creds["key_id"])

    typer.echo(f"Fetching evidence for system={system_id} framework={framework} ...")
    try:
        resp = httpx.get(f"{eff_base_url}{path}", headers=headers, timeout=30)
    except httpx.RequestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if resp.status_code == 404:
        typer.echo(f"Not found: system={system_id} framework={framework}", err=True)
        raise typer.Exit(code=1)
    if resp.status_code != 200:
        typer.echo(f"Server error {resp.status_code}: {resp.text}", err=True)
        raise typer.Exit(code=1)

    evidence_data = resp.json()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "system_id": system_id,
        "framework": framework,
        "evidence_count": len(evidence_data.get("items", [])),
        "generated_by": "sl evidence export",
    }
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("evidence.json", json.dumps(evidence_data, indent=2))

    typer.echo(f"Evidence exported to: {out_file}")
