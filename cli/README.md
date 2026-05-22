# SignalLayer CLI (`sl`)

Command-line interface for the AI Assurance Platform.

## Install

```powershell
pip install -e C:\ai-assurance-mvp\cli
```

## Authentication

```powershell
sl login --api-key <your-hmac-key>
```

Credentials are stored in `~/.signallayer/credentials.json` (mode 0600 on POSIX).
On Windows, tighten permissions manually:

```powershell
icacls "$env:USERPROFILE\.signallayer\credentials.json" /inheritance:r /grant:r "$env:USERNAME:(R,W)"
```

Override at runtime:

```powershell
$env:SL_API_KEY   = "..."
$env:SL_BASE_URL  = "http://localhost:8000"
$env:SL_KEY_ID    = "cli-dev-key"
```

## Commands

| Command | Description |
|---|---|
| `sl login --api-key <key>` | Store credentials locally |
| `sl onboard <name>` | Register a new AI system |
| `sl eval run <system-id>` | Run gate evaluation; exit 0=PASS 1=FAIL |
| `sl gate check <system-id>` | Check gate decision; exit 0=APPROVED 1=BLOCKED |
| `sl trace tail` | Stream recent trace events |
| `sl evidence export <system-id> --framework <slug> --out <path>` | Download evidence ZIP |

Global flags: `--base-url`, `--version`.

## Onboarding flow

```
User
  |
  v
sl onboard "Payments Agent" --domain payments
  |
  v
POST /api/grc/intake/submit
  |  {name, domain, business_owner, technical_owner}
  v
Platform: creates AISystem + Assessment + ReleaseGates
  |
  v
CLI prints portal URL:
  System created: ai-sys-a1b2c3d4
  Portal URL:     https://aigovern.sandboxhub.co/ai-systems?id=ai-sys-a1b2c3d4
  |
  v
(optional) Browser opens portal URL
```

## Exit codes

- `0` — success / PASS / APPROVED
- `1` — failure / FAIL / BLOCKED / error
