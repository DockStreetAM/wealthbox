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
    """Save token to credentials file. Returns the path."""
    creds_path = get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(json.dumps({"access_token": token}))
    creds_path.chmod(0o600)
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
