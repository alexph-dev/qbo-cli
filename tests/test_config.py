"""Tests for Config loading with named profiles."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from qbo_cli.cli import Config, DEFAULT_REDIRECT


def _clear_qbo_env():
    """Context manager helper: remove QBO_ env vars for clean Config tests."""
    keys = ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REDIRECT_URI", "QBO_REALM_ID", "QBO_SANDBOX"]
    old = {k: os.environ.pop(k, None) for k in keys}
    return old


def _restore_env(old: dict):
    for k, v in old.items():
        if v is not None:
            os.environ[k] = v


# ─── Profile loading ────────────────────────────────────────────────────────


class TestConfigProfileLoading:
    def test_loads_prod_profile(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {"client_id": "prod-id", "client_secret": "prod-secret"},
            "dev": {"client_id": "dev-id", "client_secret": "dev-secret"},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == "prod-id"
        assert cfg.client_secret == "prod-secret"

    def test_loads_dev_profile(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {"client_id": "prod-id", "client_secret": "prod-secret"},
            "dev": {"client_id": "dev-id", "client_secret": "dev-secret"},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="dev")
        finally:
            _restore_env(old)
        assert cfg.client_id == "dev-id"
        assert cfg.client_secret == "dev-secret"

    def test_dev_sandbox_true(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "dev": {"client_id": "x", "client_secret": "y", "sandbox": True},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="dev")
        finally:
            _restore_env(old)
        assert cfg.sandbox is True

    def test_sandbox_defaults_false(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {"client_id": "x", "client_secret": "y"},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.sandbox is False

    def test_sandbox_string_coercion(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "dev": {"client_id": "x", "client_secret": "y", "sandbox": "true"},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="dev")
        finally:
            _restore_env(old)
        assert cfg.sandbox is True


# ─── Env var overrides ───────────────────────────────────────────────────────


class TestConfigEnvOverride:
    def test_env_vars_override_profile(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {"client_id": "file-id", "client_secret": "file-secret", "realm_id": "file-realm"},
        }))
        env = {
            "QBO_CLIENT_ID": "env-id",
            "QBO_CLIENT_SECRET": "env-secret",
            "QBO_REALM_ID": "env-realm",
        }
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file), patch.dict("os.environ", env, clear=False):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == "env-id"
        assert cfg.client_secret == "env-secret"
        assert cfg.realm_id == "env-realm"

    def test_file_values_when_no_env(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {
                "client_id": "file-id",
                "client_secret": "file-secret",
                "redirect_uri": "http://custom:9999/cb",
            },
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == "file-id"
        assert cfg.client_secret == "file-secret"
        assert cfg.redirect_uri == "http://custom:9999/cb"


# ─── Missing / invalid config ───────────────────────────────────────────────


class TestConfigMissingFile:
    def test_graceful_fallback_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.json"
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == ""
        assert cfg.client_secret == ""
        assert cfg.redirect_uri == DEFAULT_REDIRECT

    def test_graceful_fallback_invalid_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("not json {{{")
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == ""


# ─── Legacy flat format ──────────────────────────────────────────────────────


class TestConfigLegacyFlat:
    def test_flat_config_warns_and_falls_back(self, tmp_path, capsys):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "client_id": "old-id",
            "client_secret": "old-secret",
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == ""  # no profile section loaded
        assert cfg.client_secret == ""
        captured = capsys.readouterr().err
        assert "legacy flat format" in captured


# ─── Missing profile in existing config ──────────────────────────────────────


class TestConfigMissingProfile:
    def test_missing_profile_falls_back_to_empty(self, tmp_path):
        """Unknown profile gets empty config (env vars can still override)."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "prod": {"client_id": "x"},
            "dev": {"client_id": "y"},
        }))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="staging")
        finally:
            _restore_env(old)
        assert cfg.client_id == ""
        assert cfg.client_secret == ""

    def test_missing_profile_with_env_override(self, tmp_path):
        """Unknown profile still honors env var overrides."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"prod": {"client_id": "x"}}))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file), \
                 patch.dict("os.environ", {"QBO_CLIENT_ID": "env-id", "QBO_CLIENT_SECRET": "env-secret"}):
                cfg = Config(profile="staging")
        finally:
            _restore_env(old)
        assert cfg.client_id == "env-id"
        assert cfg.client_secret == "env-secret"


# ─── Validate ────────────────────────────────────────────────────────────────


class TestConfigValidate:
    def test_validate_raises_when_no_client_id(self):
        cfg = Config.__new__(Config)
        cfg.profile = "prod"
        cfg.client_id = ""
        cfg.client_secret = "secret"
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_validate_raises_when_no_client_secret(self):
        cfg = Config.__new__(Config)
        cfg.profile = "prod"
        cfg.client_id = "id-only"
        cfg.client_secret = ""
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_validate_passes_when_both_set(self):
        cfg = Config.__new__(Config)
        cfg.profile = "prod"
        cfg.client_id = "test-id"
        cfg.client_secret = "test-secret"
        cfg.validate()  # should not raise


# ─── tokens_path ─────────────────────────────────────────────────────────────


class TestTokensPath:
    def test_prod_tokens_path(self):
        cfg = Config.__new__(Config)
        cfg.profile = "prod"
        assert cfg.tokens_path.name == "tokens.prod.json"

    def test_dev_tokens_path(self):
        cfg = Config.__new__(Config)
        cfg.profile = "dev"
        assert cfg.tokens_path.name == "tokens.dev.json"


# ─── Profile name validation ────────────────────────────────────────────────


class TestProfileValidation:
    @pytest.mark.parametrize("name", ["../../evil", "", "a b", "a;b"])
    def test_invalid_profile_name_dies(self, name):
        with pytest.raises(SystemExit):
            Config(profile=name)

    def test_valid_profile_names(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"my-profile_1": {"client_id": "x"}}))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file):
                cfg = Config(profile="my-profile_1")
        finally:
            _restore_env(old)
        assert cfg.profile == "my-profile_1"


# ─── QBO_SANDBOX env var rejection ──────────────────────────────────────────


class TestQboSandboxEnvRejected:
    def test_qbo_sandbox_env_true_dies(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"prod": {}}))
        with patch("qbo_cli.cli.CONFIG_PATH", config_file), \
             patch.dict("os.environ", {"QBO_SANDBOX": "true"}, clear=False):
            with pytest.raises(SystemExit):
                Config(profile="prod")

    def test_qbo_sandbox_env_false_ignored(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"prod": {"client_id": "x"}}))
        old = _clear_qbo_env()
        try:
            with patch("qbo_cli.cli.CONFIG_PATH", config_file), \
                 patch.dict("os.environ", {"QBO_SANDBOX": "false"}, clear=False):
                cfg = Config(profile="prod")
        finally:
            _restore_env(old)
        assert cfg.client_id == "x"
