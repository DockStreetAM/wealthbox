"""Regression tests for the CLI security/robustness review fixes.

Each class maps to one numbered finding in the review.
"""

import json
import os
import stat
import time
from datetime import datetime, timezone

import pytest
import responses
from click.testing import CliRunner

from wealthbox.cli.common import parse_set_fields
from wealthbox.cli.export import ExportCache, ExportMetadata, find_dirty_contacts
from wealthbox.cli.main import cli
from wealthbox.cli.output import format_csv, format_table, sanitize_text

from .test_export import (
    _register_contact_phases,
    _register_empty_activity,
    _register_empty_notes_events,
    _register_single_contact,
    _register_users_endpoint,
)

BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def split_runner():
    """Runner that keeps stderr separate from stdout."""
    # Click 8.2 removed mix_stderr (stderr is always separate there)
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _register_clean_detection():
    """Incremental change detection that finds nothing changed."""
    responses.add(responses.GET, f"{BASE_URL}contacts",
                  json={"contacts": [], "meta": {"total_pages": 1}})
    for _ in range(2):
        responses.add(responses.GET, f"{BASE_URL}tasks",
                      json={"tasks": [], "meta": {"total_pages": 1}})
    responses.add(responses.GET, f"{BASE_URL}opportunities",
                  json={"opportunities": [], "meta": {"total_pages": 1}})
    _register_empty_notes_events()


def _register_person_export(contact_id=100, name="Test Person"):
    _register_contact_phases(persons=[{"id": contact_id, "name": name, "type": "Person"}])
    _register_single_contact(contact_id, {"id": contact_id, "name": name, "type": "Person"})
    _register_users_endpoint()
    _register_empty_activity(contact_id)


# 1. export-all: failures retried, run-start timestamp, non-zero exit
class TestExportAllFailureHandling:
    @responses.activate
    def test_error_keeps_last_export_and_exits_nonzero(self, runner, mock_token, tmp_path, monkeypatch):
        out_dir = str(tmp_path / "exports")
        os.makedirs(out_dir)
        seeded = datetime(2026, 1, 20, tzinfo=timezone.utc)
        ExportMetadata(last_export=seeded).save(out_dir)

        # Contact 100 is dirty, but its export blows up (e.g. a 429)
        responses.add(responses.GET, f"{BASE_URL}contacts",
                      json={"contacts": [{"id": 100}], "meta": {"total_pages": 1}})
        for _ in range(2):
            responses.add(responses.GET, f"{BASE_URL}tasks",
                          json={"tasks": [], "meta": {"total_pages": 1}})
        responses.add(responses.GET, f"{BASE_URL}opportunities",
                      json={"opportunities": [], "meta": {"total_pages": 1}})
        _register_empty_notes_events()
        _register_contact_phases(persons=[{"id": 100, "name": "P", "type": "Person"}])

        def boom(*a, **k):
            raise RuntimeError("429 rate limited")

        monkeypatch.setattr("wealthbox.cli.export.export_contact_to_markdown", boom)

        result = runner.invoke(cli, ["contacts", "export-all", "-o", out_dir])
        assert result.exit_code == 1, result.output
        assert "Errors:" in result.output
        # Not advanced, so the next incremental run still sees contact 100 as dirty
        assert ExportMetadata.load(out_dir).last_export == seeded

    @responses.activate
    def test_last_export_is_run_start_not_end(self, runner, mock_token, tmp_path, monkeypatch):
        out_dir = str(tmp_path / "exports")
        _register_contact_phases(persons=[{"id": 100, "name": "P", "type": "Person"}])
        export_times = []

        def fake_export(*a, **k):
            time.sleep(0.01)
            export_times.append(datetime.now(timezone.utc))
            return '---\ntitle: "P"\n---\n'

        monkeypatch.setattr("wealthbox.cli.export.export_contact_to_markdown", fake_export)

        result = runner.invoke(cli, ["contacts", "export-all", "-o", out_dir])
        assert result.exit_code == 0, result.output
        # A change made mid-run (after the run started) must still be "after" last_export
        assert ExportMetadata.load(out_dir).last_export < export_times[0]


# 2. Notes/events feed incremental change detection
class TestDirtyNotesEvents:
    @responses.activate
    def test_new_note_and_event_mark_contacts_dirty(self):
        from wealthbox import WealthBox

        client = WealthBox(token="test")
        last_export = datetime(2026, 1, 20, tzinfo=timezone.utc)
        responses.add(responses.GET, f"{BASE_URL}contacts",
                      json={"contacts": [], "meta": {"total_pages": 1}})
        for _ in range(2):
            responses.add(responses.GET, f"{BASE_URL}tasks",
                          json={"tasks": [], "meta": {"total_pages": 1}})
        responses.add(responses.GET, f"{BASE_URL}opportunities",
                      json={"opportunities": [], "meta": {"total_pages": 1}})
        responses.add(responses.GET, f"{BASE_URL}notes", json={
            "status_updates": [
                {"id": 1, "created_at": "2026-01-25T10:00:00Z", "linked_to": [{"id": 300}]},
                # Old note (API ignored updated_since) must not mark 301
                {"id": 2, "created_at": "2026-01-01T10:00:00Z", "linked_to": [{"id": 301}]},
            ],
            "meta": {"total_pages": 1},
        })
        responses.add(responses.GET, f"{BASE_URL}events", json={
            "events": [{"id": 9, "updated_at": "2026-01-22T10:00:00Z", "linked_to": [{"id": 400}]}],
            "meta": {"total_pages": 1},
        })

        dirty = find_dirty_contacts(client, last_export, ExportCache())
        assert dirty == {300, 400}
        notes_call = next(c for c in responses.calls if "/notes" in c.request.url)
        assert "updated_since=" in notes_call.request.url


# 3. Rich markup injection / control chars in tables
class TestTableEscaping:
    def test_markup_is_literal_and_does_not_crash(self):
        out = format_table([
            {"name": "Acme [/] Inc"},
            {"name": "[link=http://evil.example]Click[/link]"},
        ])
        assert "Acme [/] Inc" in out
        assert "[link=http://evil.example]Click[/link]" in out
        assert "\x1b]8;" not in out  # no OSC-8 hyperlink emitted

    def test_control_chars_stripped(self):
        out = format_table([{"name": "\x1b]0;pwned\x07Bob"}])
        assert "pwned" in out  # text kept...
        assert "\x1b]0;" not in out  # ...but the escape sequence is gone

    def test_sanitize_keeps_newline_and_tab(self):
        assert sanitize_text("a\tb\nc\x1b[31md\x9b") == "a\tb\nc[31md"


# 4. CSV formula injection
class TestCsvFormulaInjection:
    def test_formula_prefixed(self):
        out = format_csv([
            {"a": '=HYPERLINK("http://evil","x")', "b": "+1", "c": "@SUM(A1)", "d": "-2"},
        ])
        row = out.splitlines()[1]
        assert row.startswith("\"'=HYPERLINK")
        assert "'+1" in row and "'@SUM(A1)" in row and "'-2" in row

    def test_real_numbers_untouched(self):
        out = format_csv([{"n": -5, "f": -1.5, "s": "plain"}])
        assert out.splitlines()[1] == "-5,-1.5,plain"


# 5. --set FIELD without '=' is rejected in every module
class TestSetParsing:
    @pytest.mark.parametrize("group", ["contacts", "tasks", "events", "notes", "opportunities", "projects"])
    @responses.activate
    def test_missing_equals_rejected(self, runner, mock_token, group):
        # No PUT registered: if one were sent it would surface as a network error
        result = runner.invoke(cli, [group, "update", "5", "--set", "first_name"])
        assert result.exit_code == 4, result.output
        assert "FIELD=VALUE" in result.output
        assert len(responses.calls) == 0

    def test_helper(self):
        assert parse_set_fields(["a=b=c", "x="]) == {"a": "b=c", "x": ""}
        with pytest.raises(Exception):
            parse_set_fields(["=v"])


# 6. Export permissions and overwrite guard
class TestExportPermissions:
    @responses.activate
    def test_export_all_perms(self, runner, mock_token, tmp_path):
        out_dir = str(tmp_path / "exports")
        _register_person_export()
        old_umask = os.umask(0o022)
        try:
            result = runner.invoke(cli, ["contacts", "export-all", "-o", out_dir])
        finally:
            os.umask(old_umask)
        assert result.exit_code == 0, result.output
        assert _mode(out_dir) == 0o700
        assert _mode(os.path.join(out_dir, "test-person-100.md")) == 0o600
        assert _mode(os.path.join(out_dir, ".export-meta.json")) == 0o600

    @responses.activate
    def test_single_export_refuses_overwrite_without_force(self, runner, mock_token, tmp_path):
        out_file = tmp_path / "client.md"
        out_file.write_text("keep me")
        result = runner.invoke(cli, ["contacts", "export", "100", "-o", str(out_file)])
        assert result.exit_code == 4
        assert "--force" in result.output
        assert out_file.read_text() == "keep me"

    @responses.activate
    def test_single_export_force_overwrites_0600(self, runner, mock_token, tmp_path):
        out_file = tmp_path / "client.md"
        out_file.write_text("old")
        os.chmod(out_file, 0o644)
        _register_single_contact(100, {"id": 100, "name": "Jane", "type": "Person"})
        _register_users_endpoint()
        _register_empty_activity(100)
        result = runner.invoke(cli, ["contacts", "export", "100", "-o", str(out_file), "--force"])
        assert result.exit_code == 0, result.output
        assert 'title: "Jane"' in out_file.read_text()
        assert _mode(out_file) == 0o600

    @responses.activate
    def test_output_option_writes_0600(self, runner, mock_token, tmp_path):
        responses.add(responses.GET, f"{BASE_URL}contacts/1", json={"id": 1})
        out_file = tmp_path / "c.json"
        result = runner.invoke(cli, ["contacts", "get", "1", "--json", "--output", str(out_file)])
        assert result.exit_code == 0, result.output
        assert _mode(out_file) == 0o600


# 7. CWD .env no longer auto-loaded (see also test_config.py)
class TestEnvFileHelp:
    def test_help_documents_env_file(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "--env-file" in result.output
        assert "NOT read automatically" in result.output


# 8. --email/--phone append behavior documented (verified live 2026-10-28)
class TestEmailPhoneHelp:
    def test_update_help_warns(self, runner):
        result = runner.invoke(cli, ["contacts", "update", "--help"])
        assert result.output.count("ADDS a new non-primary") == 2


# 9. Global --dry-run honored by export-all; notices on stderr
class TestDryRun:
    @responses.activate
    def test_global_dry_run_export_all_writes_nothing(self, runner, mock_token, tmp_path):
        out_dir = str(tmp_path / "exports")
        _register_contact_phases(persons=[{"id": 100, "name": "P", "type": "Person"}])
        result = runner.invoke(cli, ["--dry-run", "contacts", "export-all", "-o", out_dir])
        assert result.exit_code == 0, result.output
        assert "Would export" in result.output
        assert not os.path.exists(out_dir)

    def test_write_dry_run_notice_on_stderr(self, split_runner, mock_token):
        result = split_runner.invoke(
            cli, ["--dry-run", "contacts", "create", "--first-name", "A", "--json"]
        )
        assert result.exit_code == 0
        assert "Dry run" in result.stderr
        assert result.stdout == ""


# 10. --limit stops pagination
class TestListLimits:
    @pytest.mark.parametrize("group,key", [
        ("tasks", "tasks"), ("events", "events"), ("opportunities", "opportunities"),
        ("projects", "projects"), ("workflows", "workflows"),
    ])
    @responses.activate
    def test_limit_honored_and_stops_paging(self, runner, mock_token, group, key):
        responses.add(responses.GET, f"{BASE_URL}{group}", json={
            key: [{"id": i} for i in range(10)],
            "meta": {"total_pages": 5, "total_count": 50},
        })
        result = runner.invoke(cli, [group, "list", "--limit", "2", "--json"])
        assert result.exit_code == 0, result.output
        assert len(json.loads(result.output)) == 2
        assert len(responses.calls) == 1  # pages 2..5 never requested

    @responses.activate
    def test_tasks_list_keeps_default_filters(self, runner, mock_token):
        responses.add(responses.GET, f"{BASE_URL}tasks",
                      json={"tasks": [], "meta": {"total_pages": 1}})
        runner.invoke(cli, ["tasks", "list", "--completed", "--contact", "7", "--json"])
        url = responses.calls[0].request.url
        assert "completed=true" in url and "resource_id=7" in url and "resource_type=contact" in url


# 11. Escape sequences stripped from --stdout export and progress lines
class TestExportEscapes:
    @responses.activate
    def test_stdout_export_strips_escapes(self, runner, mock_token):
        _register_single_contact(5, {"id": 5, "name": "Evil\x1b]0;owned\x07 Name", "type": "Person"})
        _register_users_endpoint()
        _register_empty_activity(5)
        result = runner.invoke(cli, ["contacts", "export", "5", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "\x1b" not in result.output and "\x07" not in result.output
        assert "Evil" in result.output

    @responses.activate
    def test_progress_line_strips_escapes(self, runner, mock_token, tmp_path):
        _register_contact_phases(persons=[{"id": 5, "name": "Bad\x1b[2JName", "type": "Person"}])
        result = runner.invoke(cli, ["--dry-run", "contacts", "export-all", "-o", str(tmp_path / "x")])
        assert "\x1b" not in result.output
        assert "Bad[2JName" in result.output


# 12. Stale files removed on rename / full export
class TestStaleFiles:
    @responses.activate
    def test_rename_removes_old_file(self, runner, mock_token, tmp_path):
        out_dir = tmp_path / "exports"
        out_dir.mkdir()
        (out_dir / "old-name-100.md").write_text("stale")
        ExportMetadata(contact_files={100: "old-name-100.md"}).save(str(out_dir))
        _register_person_export(100, "New Name")
        result = runner.invoke(cli, ["contacts", "export-all", "-o", str(out_dir)])
        assert result.exit_code == 0, result.output
        assert not (out_dir / "old-name-100.md").exists()
        assert (out_dir / "new-name-100.md").exists()
        assert "old-name-100.md" in result.output

    @responses.activate
    def test_full_export_prunes_untracked_contacts(self, runner, mock_token, tmp_path):
        out_dir = tmp_path / "exports"
        out_dir.mkdir()
        (out_dir / "gone-999.md").write_text("deleted contact")
        (out_dir / "my-notes.txt").write_text("not ours")
        outside = tmp_path / "outside.md"
        outside.write_text("outside")
        ExportMetadata(
            last_export=datetime(2026, 1, 20, tzinfo=timezone.utc),
            contact_files={999: "gone-999.md", 998: "../outside.md"},
        ).save(str(out_dir))
        _register_person_export()
        result = runner.invoke(cli, ["contacts", "export-all", "-o", str(out_dir), "--full"])
        assert result.exit_code == 0, result.output
        assert not (out_dir / "gone-999.md").exists()
        assert (out_dir / "my-notes.txt").exists()
        assert outside.exists()  # metadata can't steer deletes outside the dir
        assert "Removed stale files: 1" in result.output
        assert 999 not in ExportMetadata.load(str(out_dir)).contact_files

    @responses.activate
    def test_filtered_full_export_does_not_prune(self, runner, mock_token, tmp_path):
        out_dir = tmp_path / "exports"
        out_dir.mkdir()
        (out_dir / "prospect-999.md").write_text("other type")
        ExportMetadata(contact_files={999: "prospect-999.md"}).save(str(out_dir))
        _register_person_export()
        result = runner.invoke(
            cli, ["contacts", "export-all", "-o", str(out_dir), "--full", "--contact-type", "Client"]
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "prospect-999.md").exists()


# 13. Exit-code mapping
class TestExitCodes:
    @pytest.mark.parametrize("status,code", [(404, 3), (401, 2), (403, 2), (400, 4), (422, 4)])
    @responses.activate
    def test_api_status_mapping(self, runner, mock_token, status, code):
        responses.add(responses.GET, f"{BASE_URL}contacts/1", json={"error": "x"}, status=status)
        result = runner.invoke(cli, ["--retry", "0", "contacts", "get", "1"])
        assert result.exit_code == code, result.output

    @responses.activate
    def test_delete_404_not_found(self, runner, mock_token):
        responses.add(responses.DELETE, f"{BASE_URL}contacts/1", status=404)
        result = runner.invoke(cli, ["--retry", "0", "contacts", "delete", "1", "--confirm"])
        assert result.exit_code == 3, result.output

    @responses.activate
    def test_connection_error_is_network_error(self, runner, mock_token):
        # Unregistered URL -> responses raises requests.ConnectionError
        result = runner.invoke(cli, ["--retry", "0", "--json", "contacts", "get", "1"])
        assert result.exit_code == 6, result.output
        assert "NETWORK_ERROR" in result.output

    @responses.activate
    def test_auth_test_server_error_is_not_auth_failure(self, runner, mock_token):
        responses.add(responses.GET, f"{BASE_URL}me", json={}, status=500)
        result = runner.invoke(cli, ["--retry", "0", "auth", "test"])
        assert result.exit_code == 1, result.output
        assert "Authentication failed" not in result.output

    @responses.activate
    def test_auth_test_network_error(self, runner, mock_token):
        result = runner.invoke(cli, ["--retry", "0", "auth", "test"])
        assert result.exit_code == 6, result.output
        assert "Authentication failed" not in result.output

    @responses.activate
    def test_auth_test_401_is_auth_failure(self, runner, mock_token):
        responses.add(responses.GET, f"{BASE_URL}me", json={}, status=401)
        result = runner.invoke(cli, ["--retry", "0", "auth", "test"])
        assert result.exit_code == 2
        assert "Authentication failed" in result.output


# 14. Token hygiene
class TestTokenHygiene:
    def test_no_token_message_suggests_prompt(self, runner, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: tmp_path / "nope" / "c.json")
        result = runner.invoke(cli, ["contacts", "list", "--json"])
        assert result.exit_code == 2
        assert "wb auth set-token" in result.output
        assert "<token>" not in result.output

    def test_set_token_blocked_readonly(self, runner, monkeypatch, tmp_path):
        from wealthbox.cli import config
        creds = tmp_path / "c" / "credentials.json"
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds)
        result = runner.invoke(cli, ["--readonly", "auth", "set-token"], input="tok\n")
        assert result.exit_code == 10
        assert not creds.exists()

    def test_set_token_prompt_hidden(self, split_runner, monkeypatch, tmp_path):
        from wealthbox.cli import config
        creds = tmp_path / "c" / "credentials.json"
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds)
        result = split_runner.invoke(cli, ["auth", "set-token"], input="secret_tok\n")
        assert result.exit_code == 0, result.stderr
        assert "secret_tok" not in result.stdout  # hide_input: not echoed
        assert json.loads(creds.read_text())["access_token"] == "secret_tok"

    def test_set_token_arg_warns(self, split_runner, monkeypatch, tmp_path):
        from wealthbox.cli import config
        creds = tmp_path / "c" / "credentials.json"
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds)
        result = split_runner.invoke(cli, ["auth", "set-token", "tok_arg"])
        assert result.exit_code == 0
        assert "shell history" in result.stderr
