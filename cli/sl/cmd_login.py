"""sl login — store API key in ~/.signallayer/credentials.json."""

from __future__ import annotations

import typer

from .config import DEFAULT_BASE_URL, credentials_path, save_credentials

app = typer.Typer(help="Authenticate with the SignalLayer platform.")


@app.callback(invoke_without_command=True)
def login(
    ctx: typer.Context,
    api_key: str = typer.Option(..., "--api-key", help="HMAC API key (keep secret)."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url", help="Platform base URL."),
    key_id: str = typer.Option("cli-key", "--key-id", help="Key identifier sent in X-SL-Key-Id header."),
) -> None:
    """Store HMAC credentials locally so subsequent commands authenticate automatically.

    Credentials are written to ~/.signallayer/credentials.json with mode 0600 (POSIX).
    On Windows the file is created but NTFS ACLs must be tightened manually via icacls.
    """
    path = save_credentials(api_key=api_key, base_url=base_url, key_id=key_id)
    typer.echo(f"Credentials saved to {path}")
    typer.echo("File permissions: 0600 (POSIX) — on Windows run: "
               f'icacls "{path}" /inheritance:r /grant:r "%USERNAME%:(R,W)"')
