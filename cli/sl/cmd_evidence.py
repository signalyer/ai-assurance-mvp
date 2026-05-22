"""sl evidence export — download an evidence ZIP for a system + framework."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import typer

from .auth import sign_request
from .config import load_credentials

app = typer.Typer(help="Evidence commands.")
export_app = typer.Typer(help="Export evidence packages.")
app.add_typer(export_app, name="export")


@export_app.callback(invoke_without_command=True)
def export(
    ctx: typer.Context,
    system_id: str = typer.Argument(..., help="AI system ID."),
    framework: str = typer.Option(..., "--framework", help="Framework slug (e.g. eu_ai_act, iso_42001)."),
    out: Path = typer.Option(Path("."), "--out", help="Output file path for the ZIP (directory or .zip path)."),
) -> None:
    """Download a ZIP evidence package for a system/framework combination.

    The ZIP contains evidence records and a manifest.json. The file is written
    to the path specified by --out. If --out is a directory the filename is
    auto-generated as <system_id>_<framework>_evidence.zip.
    """
    creds = load_credentials()
    base_url = ctx.obj.get("base_url") if ctx.obj else creds["base_url"]

    # Determine output file path
    if out.is_dir():
        out_file = out / f"{system_id}_{framework}_evidence.zip"
    else:
        out_file = out

    # First fetch evidence records via the evidence API
    path = f"/api/frameworks/{framework}/system/{system_id}"
    headers = sign_request(
        method="GET",
        path=path,
        body=b"",
        api_key=creds["api_key"],
        key_id=creds["key_id"],
    )

    typer.echo(f"Fetching evidence for system={system_id} framework={framework} ...")

    try:
        resp = httpx.get(f"{base_url}{path}", headers=headers, timeout=30)
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

    # Build the ZIP in memory, then write
    _write_evidence_zip(out_file, system_id, framework, evidence_data)

    typer.echo(f"Evidence exported to: {out_file}")
    _verify_zip(out_file)


def _write_evidence_zip(
    out_file: Path,
    system_id: str,
    framework: str,
    evidence_data: dict,
) -> None:
    """Write evidence data into a ZIP file with a manifest.json entry."""
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


def _verify_zip(path: Path) -> None:
    """Verify the written ZIP is valid. Prints a warning if not."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                typer.echo("Warning: ZIP written but manifest.json missing.", err=True)
    except zipfile.BadZipFile:
        typer.echo(f"Warning: file at {path} is not a valid ZIP.", err=True)
