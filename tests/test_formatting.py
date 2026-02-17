"""Tests for output formatting functions using capsys."""

from __future__ import annotations

import json

from qbo_cli.cli import _output_kv, output, output_text, output_tsv


# ─── output_text ──────────────────────────────────────────────────────────────


class TestOutputText:
    def test_list_of_dicts_table(self, capsys):
        data = [
            {"Id": "1", "Name": "Acme", "Balance": 100},
            {"Id": "2", "Name": "Beta", "Balance": 200},
        ]
        output_text(data)
        captured = capsys.readouterr().out
        assert "Id" in captured
        assert "Name" in captured
        assert "Acme" in captured
        assert "(2 rows)" in captured

    def test_single_entity_kv(self, capsys):
        data = {"Customer": {"Id": "1", "Name": "Acme", "Balance": 100}}
        output_text(data)
        captured = capsys.readouterr().out
        assert "Id" in captured
        assert "Acme" in captured

    def test_empty_list(self, capsys):
        output_text([])
        captured = capsys.readouterr().out
        assert "(no results)" in captured

    def test_non_dict_fallback(self, capsys):
        output_text(["a", "b", "c"])
        captured = capsys.readouterr().out
        # Falls through to json.dump
        assert '"a"' in captured

    def test_dict_with_nested_list(self, capsys):
        data = {"QueryResponse": {"Customer": [{"Id": "1", "Name": "Acme"}]}}
        output_text(data)
        captured = capsys.readouterr().out
        assert "Acme" in captured

    def test_flat_dict_kv_mode(self, capsys):
        data = {"Id": "1", "Name": "Test", "Active": True}
        output_text(data)
        captured = capsys.readouterr().out
        assert "Id" in captured
        assert "Test" in captured


# ─── output_tsv ───────────────────────────────────────────────────────────────


class TestOutputTsv:
    def test_list_of_dicts(self, capsys):
        data = [
            {"Id": "1", "Name": "Acme"},
            {"Id": "2", "Name": "Beta"},
        ]
        output_tsv(data)
        captured = capsys.readouterr().out
        lines = captured.strip().split("\n")
        assert lines[0] == "Id\tName"
        assert lines[1] == "1\tAcme"
        assert lines[2] == "2\tBeta"

    def test_dict_wrapper_unwrap(self, capsys):
        """output_tsv unwraps one level: finds the first list value in a dict."""
        data = {"Customer": [{"Id": "1", "Name": "Acme"}]}
        output_tsv(data)
        captured = capsys.readouterr().out
        assert "Id\tName" in captured

    def test_empty_list(self, capsys):
        output_tsv([])
        captured = capsys.readouterr().out
        assert captured == ""

    def test_plain_dict_as_single_row(self, capsys):
        data = {"Id": "1", "Name": "Acme"}
        output_tsv(data)
        captured = capsys.readouterr().out
        assert "Id\tName" in captured


# ─── _output_kv ──────────────────────────────────────────────────────────────


class TestOutputKv:
    def test_flat_dict(self, capsys):
        _output_kv({"Name": "Acme", "Id": "1"})
        captured = capsys.readouterr().out
        assert "Name" in captured
        assert "Acme" in captured

    def test_nested_dict_inline(self, capsys):
        _output_kv({"Name": "Acme", "Addr": {"City": "NYC", "State": "NY"}})
        captured = capsys.readouterr().out
        assert "City=NYC" in captured

    def test_list_values(self, capsys):
        _output_kv({"Name": "Acme", "Tags": ["a", "b"]})
        captured = capsys.readouterr().out
        assert "Tags" in captured


# ─── output (dispatch) ───────────────────────────────────────────────────────


class TestOutputDispatch:
    def test_text_format(self, capsys):
        output([{"Id": "1"}], "text")
        captured = capsys.readouterr().out
        assert "Id" in captured

    def test_tsv_format(self, capsys):
        output([{"Id": "1"}], "tsv")
        captured = capsys.readouterr().out
        assert "Id" in captured

    def test_json_format(self, capsys):
        output({"key": "val"}, "json")
        captured = capsys.readouterr().out
        parsed = json.loads(captured)
        assert parsed["key"] == "val"
