"""
One-time setup: saves your Anthropic API key to a .env file.
The key is read securely (hidden as you type) and never printed.

Usage:
    python3 scripts/setup_key.py
"""

import getpass
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

key = getpass.getpass("Paste your Anthropic API key (input is hidden): ")

if not key.startswith("sk-ant-"):
    print("Warning: key doesn't start with 'sk-ant-' — double check it's correct.")

ENV_PATH.write_text(f"ANTHROPIC_API_KEY={key}\n")
print(f"Saved to {ENV_PATH}")
print("To use it, run:  source .env  (or the test script will load it automatically)")
