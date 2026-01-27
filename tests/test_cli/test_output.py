"""Tests for CLI output formatting."""

import json
import os
import tempfile

import pytest

from wealthbox.cli.output import (
    format_csv,
    format_json,
    format_oneline,
    output,
)


SAMPLE_RECORDS = [
    {"id": 1, "name": "Alice", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"},
    {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
]


class TestFormatJson:
    def test_formats_list(self):
        result = format_json(SAMPLE_RECORDS)
        parsed = json.loads(result)
        assert len(parsed) == 3
        assert parsed[0]["name"] == "Alice"

    def test_formats_dict(self):
        result = format_json({"id": 1, "name": "Alice"})
        parsed = json.loads(result)
        assert parsed["id"] == 1

    def test_indented(self):
        result = format_json({"id": 1})
        assert "\n" in result  # Indented output


class TestFormatOneline:
    def test_one_line_per_record(self):
        result = format_oneline(SAMPLE_RECORDS)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "id" in parsed

    def test_empty_list(self):
        result = format_oneline([])
        assert result == ""


class TestFormatCsv:
    def test_csv_with_headers(self):
        result = format_csv(SAMPLE_RECORDS)
        lines = result.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows
        assert "id,name,email" in lines[0]

    def test_csv_without_headers(self):
        result = format_csv(SAMPLE_RECORDS, no_headers=True)
        lines = result.strip().split("\n")
        assert len(lines) == 3  # no header

    def test_empty_list(self):
        result = format_csv([])
        assert result == ""


class TestOutput:
    def test_json_format(self, capsys):
        output(SAMPLE_RECORDS, fmt="json")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 3

    def test_head_truncation(self, capsys):
        output(SAMPLE_RECORDS, fmt="json", head=2)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 2

    def test_count_mode(self, capsys):
        output(SAMPLE_RECORDS, count=True)
        captured = capsys.readouterr()
        assert captured.out.strip() == "3"

    def test_count_with_head(self, capsys):
        output(SAMPLE_RECORDS, count=True, head=2)
        captured = capsys.readouterr()
        assert captured.out.strip() == "2"

    def test_oneline_mode(self, capsys):
        output(SAMPLE_RECORDS, oneline=True)
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 3

    def test_fields_filter(self, capsys):
        output(SAMPLE_RECORDS, fmt="json", fields="id,name")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "email" not in parsed[0]
        assert "id" in parsed[0]
        assert "name" in parsed[0]

    def test_output_to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            output(SAMPLE_RECORDS, fmt="json", output_file=path)
            with open(path) as f:
                parsed = json.loads(f.read())
            assert len(parsed) == 3
        finally:
            os.unlink(path)

    def test_single_dict(self, capsys):
        output({"id": 1, "name": "Alice"}, fmt="json")
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["id"] == 1

    def test_csv_format(self, capsys):
        output(SAMPLE_RECORDS, fmt="csv")
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 4  # header + 3
