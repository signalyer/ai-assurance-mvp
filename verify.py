#!/usr/bin/env python
"""System verification script."""

import os
import json
import sys
from pathlib import Path

# Handle Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("\n" + "=" * 65)
print("AI ASSURANCE PLATFORM - VERIFICATION")
print("=" * 65)

errors = []
warnings = []

# Check Python files
print("\n[1/5] Python Files...")
python_files = [
    "domains.py",
    "dashboard.py",
    "api/demo_run.py",
    "multi_domain_demo.py",
]
for f in python_files:
    path = Path(f)
    if path.exists():
        print(f"  OK {f}")
    else:
        errors.append(f"Missing: {f}")
        print(f"  ERROR {f}")

# Check domain JSONs
print("\n[2/5] Domain Configurations...")
domains = ["finance", "healthcare", "legal", "education", "tech"]
domain_files = []
for d in domains:
    path = Path(f"domains/{d}.json")
    if path.exists():
        try:
            json.loads(path.read_text())
            print(f"  OK {d}.json")
            domain_files.append(d)
        except:
            errors.append(f"Invalid JSON: domains/{d}.json")
            print(f"  ERROR {d}.json (invalid JSON)")
    else:
        errors.append(f"Missing: domains/{d}.json")
        print(f"  ERROR {d}.json")

# Check environment
print("\n[3/5] Environment Configuration...")
env_file = Path(".env")
if env_file.exists():
    print(f"  OK .env file exists")
    content = env_file.read_text()
    
    has_anthropic = False
    has_openai = False
    
    if "ANTHROPIC_API_KEY=" in content:
        for line in content.split("\n"):
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=")[1].strip()
                if key and key != "sk-ant-xxxxx":
                    print(f"  OK ANTHROPIC_API_KEY configured")
                    has_anthropic = True
                    break
    
    if "OPENAI_API_KEY=" in content:
        for line in content.split("\n"):
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=")[1].strip()
                if key and key != "sk-":
                    print(f"  OK OPENAI_API_KEY configured")
                    has_openai = True
                    break
    
    if not has_anthropic:
        errors.append("ANTHROPIC_API_KEY not configured in .env")
        print(f"  ERROR ANTHROPIC_API_KEY not set")
    
    if not has_openai:
        errors.append("OPENAI_API_KEY not configured in .env")
        print(f"  ERROR OPENAI_API_KEY not set")
else:
    errors.append("Missing: .env file")
    print(f"  ERROR .env file not found")

# Check HTML
print("\n[4/5] Frontend...")
html = Path("static/index.html")
if html.exists():
    content = html.read_text()
    checks = [
        ("Domain selector", "domainSelect"),
        ("API status indicator", "apiStatus"),
        ("API health check", "checkApiHealth"),
        ("Load domains", "loadDomains"),
    ]
    for name, attr in checks:
        if attr in content:
            print(f"  OK {name}")
        else:
            errors.append(f"Missing in HTML: {attr}")
            print(f"  ERROR {name}")
else:
    errors.append("Missing: static/index.html")
    print(f"  ERROR static/index.html")

# Check documentation
print("\n[5/5] Documentation...")
docs = [
    ("Implementation Guide", "IMPLEMENTATION.md"),
    ("Quick Start", "QUICK_START.md"),
    ("Completion Summary", "COMPLETION_SUMMARY.md"),
]
for name, f in docs:
    if Path(f).exists():
        print(f"  OK {name}")
    else:
        warnings.append(f"Missing documentation: {name}")
        print(f"  WARNING {name}")

# Summary
print("\n" + "=" * 65)
if errors:
    print(f"ERRORS ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
else:
    print("NO ERRORS")

if warnings:
    print(f"\nWARNINGS ({len(warnings)}):")
    for w in warnings:
        print(f"  - {w}")
else:
    print("NO WARNINGS")

print("\n" + "=" * 65)
if not errors:
    print("SYSTEM READY - ALL CHECKS PASSED")
    print("\nTo start dashboard:")
    print("  python run.py")
    print("\nThen open: http://localhost:9007")
    print("\nTo run all domains:")
    print("  python multi_domain_demo.py")
else:
    print("SYSTEM NOT READY - FIX ERRORS BEFORE STARTING")
    print("\nCheck .env file has valid API keys:")
    print("  ANTHROPIC_API_KEY=sk-ant-...")
    print("  OPENAI_API_KEY=sk-...")
    
print("=" * 65 + "\n")
