from pathlib import Path

import pytest

from tests.conftest import pg_config
from zipzy_connector.cli import cmd_check


async def test_check_reports_each_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = pg_config("MONITOR")
    cfg = tmp_path / "connector.yaml"
    cfg.write_text(
        f"""
databases:
  - name: good
    engine: postgres
    host: {good.host}
    port: {good.effective_port}
    database: {good.database}
    user: {good.user}
    password: {good.resolve_password()}
    tls: disable
  - name: broken
    engine: postgres
    host: 127.0.0.1
    port: 1
    database: x
    user: u
    password: p
    tls: disable
""",
        encoding="utf-8",
    )
    code = await cmd_check(str(cfg))
    out = capsys.readouterr().out
    assert code == 1
    assert "OK    good" in out and "FAIL  broken" in out
    assert "database" in out.split("OK    good")[1].splitlines()[0], "catalog count is shown"
    assert good.resolve_password() not in out


async def test_check_with_bad_file(tmp_path: Path) -> None:
    assert await cmd_check(str(tmp_path / "missing.yaml")) == 2
