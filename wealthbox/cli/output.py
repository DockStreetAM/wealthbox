"""Output formatting for the WealthBox CLI."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from typing import Any

import click


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _filter_fields(data: dict, fields: list[str]) -> dict:
    """Filter a dict to only include specified fields."""
    return {k: v for k, v in data.items() if k in fields}


# C0 controls except \t and \n, DEL, and C1 controls. ESC (\x1b) is in
# here, so API-sourced text can't smuggle CSI/OSC sequences (cursor moves,
# title rewrites, OSC-8 hyperlinks) onto the user's terminal.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# Leading characters that make spreadsheet apps treat a cell as a formula
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_text(text: str) -> str:
    """Strip terminal control characters (keeps newlines and tabs)."""
    return _CONTROL_CHARS.sub("", text)


def _flatten_value(value: Any) -> str:
    """Flatten a value to a string for table/CSV display."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return sanitize_text(json.dumps(value, default=str))
    return sanitize_text(str(value))


def _csv_cell(value: Any) -> str:
    """Flatten a value for CSV, neutralizing spreadsheet formula injection.

    Per OWASP, string cells starting with = + - @ tab or CR get a leading
    single quote. Real numbers (e.g. -5) are left alone.
    """
    text = _flatten_value(value)
    if isinstance(value, str) and text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def format_json(data: Any) -> str:
    """Format data as indented JSON."""
    return json.dumps(data, indent=2, default=str)


def format_oneline(records: list[dict]) -> str:
    """Format each record as a single-line JSON object."""
    lines = [json.dumps(r, default=str) for r in records]
    return "\n".join(lines)


def format_table(records: list[dict], no_headers: bool = False) -> str:
    """Format records as a rich table, falling back to plain columns."""
    if not records:
        return ""

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        table = Table(show_header=not no_headers)
        keys = list(records[0].keys())
        for key in keys:
            table.add_column(Text(sanitize_text(str(key)).upper()))
        for record in records:
            # Text() cells are never parsed as console markup, so API data
            # like "[link=...]" or "[/]" can't style, link, or crash output
            table.add_row(*[Text(_flatten_value(record.get(k))) for k in keys])

        console = Console(file=io.StringIO(), force_terminal=True)
        console.print(table)
        return console.file.getvalue().rstrip()
    except ImportError:
        return _format_plain_table(records, no_headers)


def _format_plain_table(records: list[dict], no_headers: bool = False) -> str:
    """Plain-text table fallback when rich is not available."""
    if not records:
        return ""
    keys = list(records[0].keys())
    rows = [[_flatten_value(r.get(k)) for k in keys] for r in records]
    widths = [len(k) for k in keys]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))
    lines = []
    if not no_headers:
        header = "  ".join(k.upper().ljust(widths[i]) for i, k in enumerate(keys))
        lines.append(header)
        lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))
    return "\n".join(lines)


def format_csv(records: list[dict], no_headers: bool = False) -> str:
    """Format records as CSV."""
    if not records:
        return ""
    buf = io.StringIO()
    keys = list(records[0].keys())
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    if not no_headers:
        writer.writeheader()
    for record in records:
        writer.writerow({k: _csv_cell(record.get(k)) for k in keys})
    return buf.getvalue().rstrip()


def output(
    data: Any,
    *,
    fmt: str | None = None,
    fields: str | None = None,
    head: int | None = None,
    count: bool = False,
    oneline: bool = False,
    output_file: str | None = None,
    no_headers: bool = False,
) -> None:
    """Main output function that handles all formatting and output options.

    Args:
        data: The data to output (list of dicts, dict, or any JSON-serializable).
        fmt: Output format - 'json', 'table', 'csv', or None (auto-detect).
        fields: Comma-separated field names to include.
        head: Truncate to first N records.
        count: If True, output just the record count.
        oneline: If True, output one JSON object per line.
        output_file: If set, write to this file instead of stdout.
        no_headers: If True, omit headers in table/CSV output.
    """
    # Normalize to list for consistent processing
    is_list = isinstance(data, list)
    records = data if is_list else [data]

    # Field filtering
    if fields:
        field_list = [f.strip() for f in fields.split(",")]
        records = [_filter_fields(r, field_list) if isinstance(r, dict) else r for r in records]

    # Head truncation
    if head is not None and head > 0:
        records = records[:head]

    # Count mode
    if count:
        result = str(len(records))
        _write_output(result, output_file)
        return

    # Oneline mode
    if oneline:
        result = format_oneline(records)
        _write_output(result, output_file)
        return

    # Auto-detect format
    if fmt is None:
        fmt = "json" if not _is_tty() else "table"

    # Format output
    if fmt == "json":
        out_data = records if is_list else (records[0] if records else {})
        result = format_json(out_data)
    elif fmt == "csv":
        result = format_csv(records, no_headers=no_headers)
    elif fmt == "table":
        result = format_table(records, no_headers=no_headers)
    else:
        result = format_json(records if is_list else (records[0] if records else {}))

    _write_output(result, output_file)


def write_private_file(path: str, text: str) -> None:
    """Write text to path with owner-only (0600) permissions.

    Writes to a temp file in the same directory and renames it into place,
    so a crash can't leave a truncated file and the content is never
    readable by other users, regardless of umask.
    """
    if os.path.exists(path) and not os.path.isfile(path):
        # Device/FIFO targets like /dev/stdout can't be renamed over
        with open(path, "w") as f:
            f.write(text)
        return
    directory = os.path.dirname(os.path.abspath(path))
    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _write_output(text: str, output_file: str | None) -> None:
    """Write output to file or stdout."""
    if output_file:
        if os.path.isfile(output_file):
            click.echo(f"Warning: overwriting existing file {output_file}", err=True)
        write_private_file(output_file, text if text.endswith("\n") else text + "\n")
    else:
        click.echo(text)
