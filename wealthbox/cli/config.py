"""Token loading and configuration for the WealthBox CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path


def get_credentials_path() -> Path:
    """Get the path to the credentials file."""
    return Path.home() / ".config" / "wealthbox" / "credentials.json"


def load_token() -> str | None:
    """Load the WealthBox API token.

    Resolution order:
    1. WEALTHBOX_ACCESS_TOKEN environment variable
    2. .env file in current working directory
    3. ~/.config/wealthbox/credentials.json
    """
    # 1. Environment variable
    token = os.environ.get("WEALTHBOX_ACCESS_TOKEN")
    if token:
        return token

    # 2. .env file in current directory
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        try:
            from dotenv import dotenv_values
            values = dotenv_values(env_path)
            token = values.get("WEALTHBOX_ACCESS_TOKEN")
            if token:
                return token
        except ImportError:
            # Parse .env manually if python-dotenv not available
            token = _parse_env_file(env_path)
            if token:
                return token

    # 3. Config file
    creds_path = get_credentials_path()
    if creds_path.exists():
        try:
            data = json.loads(creds_path.read_text())
            token = data.get("access_token")
            if token:
                return token
        except (json.JSONDecodeError, OSError):
            pass

    return None


def save_token(token: str) -> Path:
    """Save token to credentials file (owner read/write only). Returns the path."""
    creds_path = get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0o600 from the start — write_text-then-chmod leaves a
    # window where the file has default umask permissions
    fd = os.open(creds_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"access_token": token}))
    creds_path.chmod(0o600)  # tighten a pre-existing file too
    return creds_path


def _parse_env_file(path: Path) -> str | None:
    """Simple .env parser for WEALTHBOX_ACCESS_TOKEN."""
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key == "WEALTHBOX_ACCESS_TOKEN":
                return value
    except OSError:
        pass
    return None
