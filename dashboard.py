"""FastAPI dashboard for AI Assurance Platform."""

import os
from pathlib import Path

# Load environment variables FIRST - before any other imports
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    env_content = env_path.read_text()
    for line in env_content.split('\n'):
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ[key] = value

from dotenv import load_dotenv
load_dotenv(dotenv_path=str(env_path), override=True)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from api.traces import router as traces_router
from api.evaluate import router as evaluate_router
from api.demo_run import router as demo_router

load_dotenv()


def validate_api_keys() -> dict[str, bool]:
    """Validate required API keys. Returns {key_name: is_valid}."""
    status = {}

    # Check Anthropic API Key
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    status["ANTHROPIC_API_KEY"] = (
        bool(anthropic_key) and
        len(anthropic_key) > 10 and
        anthropic_key.startswith("sk-ant-")
    )

    # Check OpenAI API Key
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    status["OPENAI_API_KEY"] = (
        bool(openai_key) and
        len(openai_key) > 10 and
        openai_key.startswith("sk-")
    )

    # Check Langfuse Keys (optional but recommended)
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    status["LANGFUSE"] = bool(langfuse_public) and bool(langfuse_secret)

    return status


def print_startup_status():
    """Print API key validation status on startup."""
    status = validate_api_keys()

    print("\n" + "=" * 65)
    print("API KEY VALIDATION")
    print("=" * 65)

    for key, is_valid in status.items():
        symbol = "✓" if is_valid else "✗"
        status_text = "OK" if is_valid else "MISSING"
        print(f"{symbol} {key:<25} {status_text}")

    all_required = status.get("ANTHROPIC_API_KEY") and status.get("OPENAI_API_KEY")

    print("=" * 65)
    if all_required:
        print("✓ All required keys configured. Dashboard ready.")
    else:
        print("✗ Missing required API keys. Edit .env and restart.")
    print("=" * 65 + "\n")

    return all_required


app = FastAPI(title="AI Assurance Dashboard")

# CORS for localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9007", "http://127.0.0.1:9007"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(traces_router)
app.include_router(evaluate_router)
app.include_router(demo_router)


@app.get("/api/health")
async def health_check() -> dict:
    """Return API health status and validation results."""
    status = validate_api_keys()
    all_required = status.get("ANTHROPIC_API_KEY") and status.get("OPENAI_API_KEY")
    return {
        "status": "ready" if all_required else "incomplete",
        "api_keys": status,
    }


@app.get("/")
async def serve_dashboard() -> FileResponse:
    """Serve the main dashboard HTML."""
    static_dir = Path(__file__).parent / "static"
    return FileResponse(static_dir / "index.html", media_type="text/html")


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 65)
    print("AI ASSURANCE DASHBOARD")
    print("=" * 65)
    print("Dashboard running at http://localhost:9007")
    print("=" * 65 + "\n")

    # Validate API keys on startup
    all_configured = print_startup_status()

    uvicorn.run(app, host="127.0.0.1", port=9007, log_level="info")
