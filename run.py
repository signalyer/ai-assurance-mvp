#!/usr/bin/env python
"""One-command startup script for AI Assurance Dashboard."""

import sys
import subprocess
import time
import webbrowser
from pathlib import Path

def check_env():
    """Check if .env file exists, create from example and local.env if not."""
    env_file = Path(".env")
    env_example = Path(".env.example")
    local_env = Path("local.env")

    if not env_file.exists():
        if env_example.exists():
            print("Creating .env from .env.example...")
            env_content = env_example.read_text()

            # If local.env exists, merge API keys
            if local_env.exists():
                print("Found local.env - merging API keys...")
                local_content = local_env.read_text()

                # Extract API keys from local.env
                keys_found = []
                for line in local_content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        key_name, key_value = line.split('=', 1)

                        # Replace in env_content
                        if key_name == 'ANTHROPIC_API_KEY':
                            env_content = env_content.replace(
                                'ANTHROPIC_API_KEY=sk-ant-xxxxx',
                                f'{line}'
                            )
                            keys_found.append('ANTHROPIC_API_KEY')
                        elif key_name == 'LANGFUSE_SECRET_KEY':
                            env_content = env_content.replace(
                                'LANGFUSE_SECRET_KEY=sk_xxxxx',
                                f'{line}'
                            )
                            keys_found.append('LANGFUSE_SECRET_KEY')
                        elif key_name == 'LANGFUSE_PUBLIC_KEY':
                            env_content = env_content.replace(
                                'LANGFUSE_PUBLIC_KEY=pk_xxxxx',
                                f'{line}'
                            )
                            keys_found.append('LANGFUSE_PUBLIC_KEY')
                        elif key_name == 'LANGFUSE_BASE_URL':
                            env_content = env_content.replace(
                                'LANGFUSE_HOST=https://cloud.langfuse.com',
                                f'{key_name}={key_value}'
                            )
                            keys_found.append('LANGFUSE_BASE_URL')

                if keys_found:
                    print(f"✓ Loaded {', '.join(keys_found)} from local.env")

            env_file.write_text(env_content)

            # Check if all required keys are present
            has_all_keys = (
                'LANGFUSE_PUBLIC_KEY=pk_' in env_content or 'LANGFUSE_PUBLIC_KEY=' in env_content
            ) and 'ANTHROPIC_API_KEY=sk-ant-' in env_content

            if not has_all_keys:
                print("\nWARNING: Missing some API keys in .env")
                print("You need to fill in:")
                if 'LANGFUSE_PUBLIC_KEY=pk_' not in env_content:
                    print("  - LANGFUSE_PUBLIC_KEY (from https://cloud.langfuse.com)")
                    print("  - LANGFUSE_SECRET_KEY")
                if 'OPENAI_API_KEY=' not in env_content:
                    print("  - OPENAI_API_KEY (from https://platform.openai.com)")
                print("\nEdit .env and add these keys, then run again.\n")
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
