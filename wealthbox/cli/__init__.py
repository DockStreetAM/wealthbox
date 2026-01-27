"""WealthBox CLI - Command line interface for WealthBox CRM."""

try:
    import click  # noqa: F401
except ImportError:
    raise ImportError(
        "CLI dependencies not installed. Install with: pip install wealthbox[cli]"
    )
