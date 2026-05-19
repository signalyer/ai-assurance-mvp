"""FastAPI dashboard for AI Assurance Platform."""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from api.traces import router as traces_router
from api.evaluate import router as evaluate_router
from api.demo_run import router as demo_router

load_dotenv()

app = FastAPI(title="AI Assurance Dashboard")

# CORS for localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(traces_router)
app.include_router(evaluate_router)
app.include_router(demo_router)


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
    print("\nStarting dashboard server...")
    print("Open browser to: http://localhost:8000")
    print("=" * 65 + "\n")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
