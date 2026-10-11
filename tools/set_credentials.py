#!/usr/bin/env python3
"""Store your portal login for amido_laundry.py without it ever appearing in shell history or chat.

Usage (on the machine/container that runs Home Assistant):
    python3 tools/set_credentials.py [/config]

The file is created chmod 600. Never commit it, never paste it anywhere.
"""
import getpass
import json
import os
import sys

target = os.path.join(sys.argv[1] if len(sys.argv) > 1 else "/config", "amido_credentials.json")
user = input("Login (as used at your landlord's portal): ").strip()
password = getpass.getpass("Password (hidden): ")
if not user or not password:
    sys.exit("Nothing saved: both fields are required.")
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump({"username": user, "password": password}, f)
print(f"Saved to {target} (chmod 600).")
