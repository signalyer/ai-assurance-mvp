"""sl trace tail — stream SSE trace events from the platform."""

from __future__ import annotations

import signal
import sys

import httpx
import typer

from .auth import sign_request
from .config import load_credentials

app = typer.Typer(help="Trace streaming commands.")
tail_app = typer.Typer(help="Tail live trace events.")
app.add_typer(tail_app, name="tail")


@tail_app.callback(invoke_without_command=True)
def tail(
    ctx: typer.Context,
    system: str = typer.Option("", "--system", help="Filter to a specific system ID (optional)."),
    limit: int = typer.Option(50, "--limit", help="Maximum number of events to print before stopping."),
) -> None:
    """Connect to the platform SSE traces endpoint and print events as they arrive.

    Press Ctrl+C to stop.

    The endpoint consumed is GET /api/traces, which returns the most recent cached
    traces. This command polls repeatedly until --limit events have been seen or
    Ctrl+C is pressed.
    """
    creds = load_credentials()
    base_url = ctx.obj.get("base_url") if ctx.obj else creds["base_url"]

    path = "/api/traces"
    headers = sign_request(
        method="GET",
        path=path,
        body=b"",
        api_key=creds["api_key"],
        key_id=creds["key_id"],
    )

    typer.echo("Tailing traces (Ctrl+C to stop) ...")

    seen_ids: set[str] = set()
    count = 0

    def _handle_signal(signum: int, frame: object) -> None:
        typer.echo("\nStopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)

    try:
        with httpx.stream("GET", f"{base_url}{path}", headers=headers, timeout=30) as resp:
            if resp.status_code != 200:
                typer.echo(f"Error: server returned {resp.status_code}", err=True)
                raise typer.Exit(code=1)

            data = resp.read()
            import json
            parsed = json.loads(data)
            traces = parsed.get("traces", [])

            for trace in traces:
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

    typer.echo(f"Done — {count} event(s) shown.")
