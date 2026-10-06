"""Console entry point for the dope.security MCP server."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import structlog

from dopesecurity.mcp_server.config import (
    CliConfigOverrides,
    configure_logging,
    load_settings,
)

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dopesecurity-mcp-server",
        description=(
            "Local MCP server for the dope.security Flightdeck partner API. "
            "Reads credentials from DOPE_CLIENT_ID and DOPE_CLIENT_SECRET."
        ),
    )
    parser.add_argument(
        "--enable-mutations",
        action="store_true",
        default=None,
        help="Expose write tools that modify tenant state.",
    )
    parser.add_argument(
        "--enable-destructive",
        action="store_true",
        default=None,
        help=(
            "Additionally expose destructive tools that drop a whole policy or "
            "custom category, or reset whole sections to base. Requires "
            "--enable-mutations."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        metavar="FLOAT",
        help="HTTP timeout for Flightdeck calls in seconds.",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVEL_CHOICES,
        default=None,
        help="Logging verbosity. Logs are written to stderr.",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "If set, also append JSON logs to this file (handy when running "
            "under MCP Inspector, which hides server stderr)."
        ),
    )
    parser.add_argument(
        "--token-refresh-skew-seconds",
        type=float,
        default=None,
        metavar="FLOAT",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        metavar="URL",
        help=argparse.SUPPRESS,
    )
    return parser


def _overrides_from_args(args: argparse.Namespace) -> CliConfigOverrides:
    return CliConfigOverrides(
        enable_mutations=args.enable_mutations,
        enable_destructive=args.enable_destructive,
        timeout_seconds=args.timeout_seconds,
        log_level=args.log_level,
        token_refresh_skew_seconds=args.token_refresh_skew_seconds,
        base_url=args.base_url,
        log_file=args.log_file,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    overrides = _overrides_from_args(args)
    settings = load_settings(overrides)
    configure_logging(settings.log_level, log_file=settings.log_file)

    log = structlog.get_logger("dopesecurity.mcp_server.main")
    # WARNING: client_id and base url logged in clear text on purpose for
    # debugging credential issues; tighten before production.
    log.info(
        "main.startup",
        log_level=settings.log_level,
        api_base_url=settings.api_base_url,
        enable_mutations=settings.enable_mutations,
        enable_destructive=settings.enable_destructive,
        timeout_seconds=settings.timeout_seconds,
        token_refresh_skew_seconds=settings.token_refresh_skew_seconds,
        client_id=settings.client_id,
        client_secret_set=bool(settings.client_secret.get_secret_value()),
        client_secret_length=len(settings.client_secret.get_secret_value()),
    )

    # Imported lazily so --help does not require constructing MCPServer.
    from dopesecurity.mcp_server.server import create_server

    try:
        mcp = create_server(settings)
        mcp.run()
    except Exception as exc:
        log.exception(
            "main.fatal",
            exc_type=type(exc).__name__,
            exc_message=str(exc),
        )
        raise
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
