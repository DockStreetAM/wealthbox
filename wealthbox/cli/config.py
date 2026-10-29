"""Token loading and configuration for the WealthBox CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path


def get_credentials_path() -> Path:
    """Get the path to the credentials file."""
    return Path.home() / ".config" / "wealthbox" / "credentials.json"


def get_config_env_path() -> Path:
    """Path of the optional .env file in the config directory."""
    return get_credentials_path().parent / ".env"


def _token_from_env_file(env_path: Path) -> str | None:
    """Read WEALTHBOX_ACCESS_TOKEN from a .env file, if present."""
    if not env_path.is_file():
        return None
    try:
        from dotenv import dotenv_values
        return dotenv_values(env_path).get("WEALTHBOX_ACCESS_TOKEN") or None
    except ImportError:
        # Parse .env manually if python-dotenv not available
        return _parse_env_file(env_path)


def load_token(env_file: str | os.PathLike | None = None) -> str | None:
    """Load the WealthBox API token.

    Resolution order:
    1. WEALTHBOX_ACCESS_TOKEN environment variable
    2. An explicitly requested .env file (``wb --env-file PATH``)
    3. ~/.config/wealthbox/credentials.json (written by ``wb auth set-token``)
    4. ~/.config/wealthbox/.env

    A .env in the current working directory is deliberately NOT read: a
    cloned repo shipping its own .env could otherwise silently swap in a
    different workspace's token. Pass ``--env-file .env`` to opt in.
    """
    # 1. Environment variable
    token = os.environ.get("WEALTHBOX_ACCESS_TOKEN")
    if token:
        return token

    # 2. Explicit .env file
    if env_file is not None:
        token = _token_from_env_file(Path(env_file))
        if token:
            return token

    # 3. Credentials file
    creds_path = get_credentials_path()
    if creds_path.exists():
        try:
            data = json.loads(creds_path.read_text())
            token = data.get("access_token")
            if token:
                return token
        except (json.JSONDecodeError, OSError):
            pass

    # 4. .env in the config directory
    return _token_from_env_file(get_config_env_path())


def _cwd_env_has_token() -> bool:
    """True if ./.env defines WEALTHBOX_ACCESS_TOKEN (value is never returned)."""
    return bool(_token_from_env_file(Path.cwd() / ".env"))


def no_token_message() -> str:
    """Explain why no token was found and how to fix it.

    Calls out the 0.18.0 change explicitly when the user still has a token
    in ./.env, since that used to be read automatically.
    """
    msg = (
        "No API token found. Save one with `wb auth set-token` (run it in a "
        "terminal; it prompts with hidden input) or set WEALTHBOX_ACCESS_TOKEN."
    )
    if _cwd_env_has_token():
        msg += (
            " Note: ./.env contains WEALTHBOX_ACCESS_TOKEN, but since wealthbox "
            "0.18.0 a .env in the current directory is no longer read "
            "automatically. Either pass it explicitly (`wb --env-file .env ...`) "
            "or store it once: `wb auth set-token --from-env .env`."
        )
    return msg


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
