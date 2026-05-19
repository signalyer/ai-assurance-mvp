#!/usr/bin/env python
"""Fresh start script - kills old processes and starts clean."""

import subprocess
import sys
import time
import os
import signal

def kill_old_processes():
    """Kill any old Python processes on port 9007."""
    try:
        # Windows: taskkill
        subprocess.run(
            ['taskkill', '/F', '/IM', 'python.exe'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        print("Killed old Python processes")
    except:
        pass

    time.sleep(2)

def clear_cache():
    """Clear Python cache directories."""
    for root, dirs, files in os.walk('.'):
        if '__pycache__' in dirs:
            try:
                import shutil
                path = os.path.join(root, '__pycache__')
                shutil.rmtree(path, ignore_errors=True)
            except:
                pass

def start_dashboard():
    """Start the dashboard."""
    print("\n" + "=" * 70)
    print("AI ASSURANCE DASHBOARD - FRESH START")
    print("=" * 70)
    print("\nDashboard starting on: http://localhost:9007")
    print("\nPress CTRL+C to stop\n")

    # Start the server
    os.system('python dashboard.py')

if __name__ == "__main__":
    kill_old_processes()
    clear_cache()
    start_dashboard()
