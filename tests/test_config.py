"""Tests for Config loading and env var overrides."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from qbo_cli.cli import Config, DEFAULT_REDIRECT


# ─── Config loading ───────────────────────────────────────────────────────────


class TestConfigEnvOverride:
    def test_env_vars_override_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "client_id": "file-id",
            "client_secret": "file-secret",
            "realm_id": "file-realm",
        }))

        env = {
            "QBO_CLIENT_ID": "env-id",
            "QBO_CLIENT_SECRET": "env-secret",
            "QBO_REALM_ID": "env-realm",
        }

        with patch("qbo_cli.cli.CONFIG_PATH", config_file), patch.dict("os.environ", env, clear=False):
            cfg = Config()

        assert cfg.client_id == "env-id"
        assert cfg.client_secret == "env-secret"
        assert cfg.realm_id == "env-realm"

    def test_file_values_when_no_env(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "client_id": "file-id",
            "client_secret": "file-secret",
            "redirect_uri": "http://custom:9999/cb",
        }))

        env_clear = {"QBO_CLIENT_ID": "", "QBO_CLIENT_SECRET": "", "QBO_REDIRECT_URI": "", "QBO_REALM_ID": "", "QBO_SANDBOX": ""}
        with patch("qbo_cli.cli.CONFIG_PATH", config_file), patch.dict("os.environ", {}, clear=False):
            # Remove QBO_ vars from env
            import os
            old = {k: os.environ.pop(k, None) for k in env_clear}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v

        assert cfg.client_id == "file-id"
        assert cfg.client_secret == "file-secret"
        assert cfg.redirect_uri == "http://custom:9999/cb"


class TestConfigMissingFile:
    def test_graceful_fallback_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.json"
        with patch("qbo_cli.cli.CONFIG_PATH", config_file):
            import os
            old = {k: os.environ.pop(k, None) for k in ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v

        assert cfg.client_id == ""
        assert cfg.client_secret == ""
        assert cfg.redirect_uri == DEFAULT_REDIRECT

    def test_graceful_fallback_invalid_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("not json {{{")
        with patch("qbo_cli.cli.CONFIG_PATH", config_file):
            import os
            old = {k: os.environ.pop(k, None) for k in ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v

        assert cfg.client_id == ""


class TestConfigValidate:
    def test_validate_raises_when_no_client_id(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"client_secret": "secret"}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file):
            import os
            old = {k: os.environ.pop(k, None) for k in ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_validate_raises_when_no_client_secret(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"client_id": "id-only"}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file):
            import os
            old = {k: os.environ.pop(k, None) for k in ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_validate_passes_when_both_set(self):
        cfg = Config.__new__(Config)
        cfg.client_id = "test-id"
        cfg.client_secret = "test-secret"
        cfg.validate()  # should not raise


class TestConfigSandbox:
    def test_sandbox_bool(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"sandbox": True}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file):
            import os
            old = {k: os.environ.pop(k, None) for k in ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]}
            try:
                cfg = Config()
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v

        assert cfg.sandbox is True

    def test_sandbox_string_true(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file), patch.dict("os.environ", {"QBO_SANDBOX": "true"}, clear=False):
            cfg = Config()

        assert cfg.sandbox is True

    def test_sandbox_string_false(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file), patch.dict("os.environ", {"QBO_SANDBOX": "no"}, clear=False):
            cfg = Config()

        assert cfg.sandbox is False
