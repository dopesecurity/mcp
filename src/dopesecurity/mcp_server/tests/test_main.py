"""Tests for the console entry point."""

from __future__ import annotations

import pytest

from dopesecurity.mcp_server.__main__ import main


def test_main_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    capsys.readouterr()
