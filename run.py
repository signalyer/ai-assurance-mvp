#!/usr/bin/env python
"""One-command startup script for AI Assurance Dashboard."""

import sys
import subprocess
import time
import webbrowser
from pathlib import Path

def check_env():
    """Check if .env file exists, create from example if not."""
    env_file = Path(".env")
    env_example = Path(".env.example")

    if not env_file.exists():
        if env_example.exists():
            print("Creating .env from .env.example...")
            env_file.write_text(env_example.read_text())
            print("WARNING: .env created but you need to fill in your API keys!")
            print("Edit .env and add:")
            print("  - LANGFUSE_PUBLIC_KEY")
            print("  - LANGFUSE_SECRET_KEY")
            print("  - ANTHROPIC_API_KEY")
            print("  - OPENAI_API_KEY")
            print()
        else:
            print("ERROR: .env.example not found")
            sys.exit(1)

def install_dependencies():
    """Install Python dependencies."""
    print("Checking dependencies...")
    try:
        import langfuse
        import deepeval
        import fastapi
        print("Dependencies already installed")
    except ImportError:
        print("Installing dependencies...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
            check=True,
        )
        print("Dependencies installed")

def start_dashboard():
    """Start the dashboard server."""
    print("\nStarting dashboard...")
    print("=" * 65)
    print("AI ASSURANCE DASHBOARD")
    print("=" * 65)
    print("\nDashboard running at: http://localhost:9007")
    print("Press CTRL+C to stop\n")

    # Start the server
    subprocess.run([sys.executable, "dashboard.py"])

if __name__ == "__main__":
    try:
        check_env()
        install_dependencies()

        # Wait a moment then open browser
        print("\nOpening browser in 2 seconds...")
        time.sleep(2)

        # Open browser
        webbrowser.open("http://localhost:9007")

        # Start dashboard
        start_dashboard()

    except KeyboardInterrupt:
        print("\n\nDashboard stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
