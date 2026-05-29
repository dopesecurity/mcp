"""Tests for configuration loading and CLI overrides."""

from __future__ import annotations

import argparse
import dataclasses

import pytest
from pydantic import SecretStr, ValidationError

from dopesecurity.mcp_server.__main__ import _build_parser
from dopesecurity.mcp_server.config import (
    DEFAULT_BASE_URL,
    CliConfigOverrides,
    load_settings,
)

REQUIRED_ENV = {
    "DOPE_CLIENT_ID": "test-client-id",
    "DOPE_CLIENT_SECRET": "test-client-secret",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    # Wipe DOPE_* keys so tests stay isolated.
    for key in list(REQUIRED_ENV) + [
        "DOPE_ENABLE_MUTATIONS",
        "DOPE_ENABLE_DESTRUCTIVE",
        "DOPE_TIMEOUT_SECONDS",
        "DOPE_LOG_LEVEL",
        "DOPE_TOKEN_REFRESH_SKEW_SECONDS",
        "DOPE_BASE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_settings_loads_required_env_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, REQUIRED_ENV)

    settings = load_settings()

    assert settings.client_id == "test-client-id"
    assert isinstance(settings.client_secret, SecretStr)
    assert settings.client_secret.get_secret_value() == "test-client-secret"
    assert settings.enable_mutations is False
    assert settings.enable_destructive is False
    assert settings.timeout_seconds == 30.0
    assert settings.log_level == "INFO"
    assert settings.token_refresh_skew_seconds == 60.0
    assert settings.api_base_url == DEFAULT_BASE_URL


def test_destructive_env_without_mutations_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        {**REQUIRED_ENV, "DOPE_ENABLE_DESTRUCTIVE": "true"},
    )

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    assert "destructive" in str(excinfo.value).lower()


def test_destructive_cli_without_mutations_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, REQUIRED_ENV)

    with pytest.raises(ValueError, match="destructive"):
        load_settings(CliConfigOverrides(enable_destructive=True))


def test_destructive_enabled_with_mutations_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        {
            **REQUIRED_ENV,
            "DOPE_ENABLE_MUTATIONS": "true",
            "DOPE_ENABLE_DESTRUCTIVE": "true",
        },
    )

    settings = load_settings()

    assert settings.enable_mutations is True
    assert settings.enable_destructive is True


def test_settings_rejects_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, {})

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    rendered = str(excinfo.value)
    assert "DOPE_CLIENT_ID" in rendered
    assert "DOPE_CLIENT_SECRET" in rendered
    # Make sure no secret-looking value sneaks into the rendered error.
    assert "test-client-secret" not in rendered


def test_cli_overrides_non_secret_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, REQUIRED_ENV)
    overrides = CliConfigOverrides(
        enable_mutations=True,
        timeout_seconds=5.5,
        log_level="debug",
        token_refresh_skew_seconds=10.0,
        base_url="https://internal.example.com/v1",
    )

    settings = load_settings(overrides)

    assert settings.enable_mutations is True
    assert settings.timeout_seconds == 5.5
    assert settings.log_level == "DEBUG"
    assert settings.token_refresh_skew_seconds == 10.0
    assert settings.api_base_url == "https://internal.example.com/v1"


def test_secret_cannot_be_set_from_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, REQUIRED_ENV)

    field_names = {f.name for f in dataclasses.fields(CliConfigOverrides)}
    assert "client_id" not in field_names
    assert "client_secret" not in field_names

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--client-secret", "should-not-work"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--client-id", "should-not-work"])


def test_empty_env_values_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        {
            **REQUIRED_ENV,
            "DOPE_LOG_LEVEL": "",
            "DOPE_TIMEOUT_SECONDS": "",
        },
    )

    settings = load_settings()

    assert settings.log_level == "INFO"
    assert settings.timeout_seconds == 30.0


def test_cli_does_not_define_secret_flags() -> None:
    parser = _build_parser()
    actions = {a.dest for a in parser._actions if isinstance(a, argparse.Action)}
    assert "client_id" not in actions
    assert "client_secret" not in actions
