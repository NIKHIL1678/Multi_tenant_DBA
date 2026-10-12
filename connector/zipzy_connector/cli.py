"""Command line.

    zipzy-connector check   test every database in connector.yaml from this server
                            (no ZipZy needed)
    zipzy-connector run     enrol on first start, then stay connected to ZipZy and answer
                            its allow-listed, read-only requests

Exit codes: 0 ok, 1 a database is unreachable (check), 2 configuration or enrolment problem.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from zipzy_connector import __version__, gateway, log
from zipzy_connector.config import (
    ConfigError,
    ConnectorFile,
    Settings,
    default_config_path,
    load_file,
)
from zipzy_connector.engines import ProbeResult, probe
from zipzy_connector.identity import EnrollmentError, ensure_enrolled


async def probe_all(config: ConnectorFile) -> list[ProbeResult]:
    return list(await asyncio.gather(*(probe(db) for db in config.databases)))


def _print_table(results: list[ProbeResult]) -> None:
    if not results:
        print("No databases in the settings file yet.")
        return
    width = max(len(r.name) for r in results)
    for r in results:
        status = "OK  " if r.reachable else "FAIL"
        detail = f"{r.engine} {r.version}" if r.reachable else (r.error or "unreachable")
        warning = ""
        if r.reachable and r.capabilities.get("least_privilege") is False:
            warning = "  (warning: this user can change data; use a read-only monitoring user)"
        print(f"{status}  {r.name.ljust(width)}  {detail}{warning}")


async def cmd_check(config_path: str | None) -> int:
    # No ZipZy address needed: this only tests the databases from this server.
    try:
        config = load_file(Path(config_path) if config_path else default_config_path())
    except ConfigError as exc:
        print(f"Configuration problem: {exc}", file=sys.stderr)
        return 2
    results = await probe_all(config)
    _print_table(results)
    return 0 if all(r.reachable for r in results) else 1


async def cmd_run() -> int:
    try:
        settings = Settings.from_env()
        config = load_file(settings.config_path)
    except ConfigError as exc:
        log.error("configuration problem", detail=str(exc))
        return 2

    log.info("starting", version=__version__, databases=len(config.databases))
    async with httpx.AsyncClient() as client:
        try:
            identity, new = await ensure_enrolled(
                client,
                data_dir=settings.data_dir,
                zipzy_url=settings.zipzy_url,
                token=settings.enroll_token,
                version=__version__,
            )
        except EnrollmentError as exc:
            log.error("enrolment failed", detail=str(exc))
            return 2
    log.info("enrolled" if new else "identity loaded", connector_id=identity.connector_id)

    for r in await probe_all(config):
        fields = {"database": r.name, "engine": r.engine, "version": r.version}
        if r.reachable:
            log.info("database reachable", **fields, capabilities=r.capabilities)
        else:
            log.warn("database unreachable", **fields, reason=r.error)
    return await gateway.run_forever(settings.zipzy_url, identity, config)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="zipzy-connector", description="ZipZy DBA connector")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="test every database in the settings file")
    check.add_argument(
        "--config", help="path to connector.yaml (default: $ZIPZY_CONFIG or /config/connector.yaml)"
    )
    sub.add_parser("run", help="enrol, then stay connected to ZipZy")
    args = parser.parse_args(argv)

    if args.command == "check":
        code = asyncio.run(cmd_check(args.config))
    else:
        try:
            code = asyncio.run(cmd_run())
        except KeyboardInterrupt:
            code = 0
    sys.exit(code)
