"""Runtime configuration and logging setup."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DEFAULT_BASE_URL = "https://api.flightdeck.dope.security/v1"


@dataclass(frozen=True)
class CliConfigOverrides:
    """CLI overrides for non-secret settings."""

    enable_mutations: bool | None = None
    enable_destructive: bool | None = None
    timeout_seconds: float | None = None
    log_level: str | None = None
    token_refresh_skew_seconds: float | None = None
    base_url: str | None = None
    log_file: str | None = None


class Settings(BaseSettings):
    """Process-wide settings sourced from the environment with optional overrides."""

    model_config = SettingsConfigDict(
        env_prefix="DOPE_",
        env_ignore_empty=True,
        extra="forbid",
        case_sensitive=False,
    )

    client_id: str = Field(validation_alias="DOPE_CLIENT_ID")
    client_secret: SecretStr = Field(validation_alias="DOPE_CLIENT_SECRET")
    enable_mutations: bool = Field(default=False, validation_alias="DOPE_ENABLE_MUTATIONS")
    enable_destructive: bool = Field(
        default=False, validation_alias="DOPE_ENABLE_DESTRUCTIVE"
    )
    timeout_seconds: float = Field(default=30.0, validation_alias="DOPE_TIMEOUT_SECONDS", gt=0)
    log_level: LogLevel = Field(default="INFO", validation_alias="DOPE_LOG_LEVEL")
    token_refresh_skew_seconds: float = Field(
        default=60.0, validation_alias="DOPE_TOKEN_REFRESH_SKEW_SECONDS", ge=0
    )
    api_base_url: str = Field(default=DEFAULT_BASE_URL, validation_alias="DOPE_BASE_URL")
    log_file: str | None = Field(default=None, validation_alias="DOPE_LOG_FILE")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.upper()
        return value

    @model_validator(mode="after")
    def _destructive_requires_mutations(self) -> Settings:
        if self.enable_destructive and not self.enable_mutations:
            raise ValueError(
                "DOPE_ENABLE_DESTRUCTIVE requires DOPE_ENABLE_MUTATIONS to also "
                "be enabled (destructive tools are a subset of write tools)."
            )
        return self


def load_settings(overrides: CliConfigOverrides | None = None) -> Settings:
    """Load settings from environment, then apply non-secret CLI overrides."""

    settings = Settings()  # type: ignore[call-arg]
    if overrides is None:
        return settings

    update: dict[str, Any] = {}
    if overrides.enable_mutations is not None:
        update["enable_mutations"] = overrides.enable_mutations
    if overrides.enable_destructive is not None:
        update["enable_destructive"] = overrides.enable_destructive
    if overrides.timeout_seconds is not None:
        update["timeout_seconds"] = overrides.timeout_seconds
    if overrides.log_level is not None:
        update["log_level"] = overrides.log_level.upper()
    if overrides.token_refresh_skew_seconds is not None:
        update["token_refresh_skew_seconds"] = overrides.token_refresh_skew_seconds
    if overrides.base_url is not None:
        update["api_base_url"] = overrides.base_url
    if overrides.log_file is not None:
        update["log_file"] = overrides.log_file

    if not update:
        return settings
    merged = settings.model_copy(update=update)
    # model_copy bypasses validators; re-check the destructive invariant
    # so CLI flags like `--enable-destructive` (without --enable-mutations)
    # fail loudly at startup instead of silently registering nothing.
    if merged.enable_destructive and not merged.enable_mutations:
        raise ValueError(
            "--enable-destructive requires --enable-mutations to also be "
            "enabled (destructive tools are a subset of write tools)."
        )
    return merged


class _TeeWriter:
    """File-like sink that writes/flushes to multiple underlying streams."""

    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        last = 0
        for stream in self._streams:
            try:
                last = stream.write(data)
            except Exception:  # noqa: BLE001 - never let logging break the app
                pass
        return last

    def flush(self) -> None:
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:  # noqa: BLE001
                pass


def configure_logging(log_level: str, log_file: str | None = None) -> None:
    """Configure stdlib logging and structlog to write to stderr (and optional file)."""

    level_name = log_level.upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    sink: Any = sys.stderr
    if log_file:
        # Line-buffered so `tail -f` shows entries as they happen.
        file_stream = open(log_file, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
        sink = _TeeWriter(sys.stderr, file_stream)
        # Surface the path so users know where to tail.
        print(f"dopesecurity-mcp-server: logging to {log_file}", file=sys.stderr)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # NOTE: `dict_tracebacks` includes full traceback frames, locals, and
            # the exception chain. This is intentionally verbose for debugging
            # auth/credential issues and may leak sensitive data; tighten before
            # production hardening.
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sink),
        cache_logger_on_first_use=True,
    )
