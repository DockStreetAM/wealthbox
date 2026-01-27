"""Entry point for python -m wealthbox."""

try:
    from wealthbox.cli.main import cli
except ImportError:
    import sys
    print(
        "CLI dependencies not installed. Install with: pip install wealthbox[cli]",
        file=sys.stderr,
    )
    sys.exit(1)

cli()
