"""Command-line entry point for ibtop."""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .formatting import LogBarTableFormatter
from .model import SORT_KEYS, RateCalculator, sort_metrics
from .sysfs import INFINIBAND_SYSFS_ROOT, SysfsReader
from .ui import CursesDashboard


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser shared by console script and tests."""
    parser = argparse.ArgumentParser(
        prog="ibtop",
        description="Python-only InfiniBand top-style monitor for Linux sysfs counters.",
    )
    parser.add_argument(
        "-r",
        "--refresh",
        type=float,
        default=1.0,
        help="refresh interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-e",
        "--ethernet",
        action="store_true",
        help="include Ethernet link-layer RDMA ports",
    )
    parser.add_argument(
        "--history",
        type=int,
        default=60,
        help="per-interface graph history length in samples (default: 60)",
    )
    parser.add_argument(
        "--sysfs",
        type=Path,
        default=INFINIBAND_SYSFS_ROOT,
        help=f"InfiniBand sysfs root (default: {INFINIBAND_SYSFS_ROOT})",
    )
    parser.add_argument(
        "--sort",
        choices=SORT_KEYS,
        default="name",
        help="initial interface sort order",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="print one LogBar-formatted snapshot and exit",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on unreadable or malformed sysfs counter files",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="LogBar level for one-shot output (default: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ibtop {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run either the live dashboard or one-shot output."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.refresh <= 0:
        parser.error("--refresh must be greater than 0")
    if args.history < 2:
        parser.error("--history must be at least 2")
    if platform.system() != "Linux":
        parser.error("ibtop currently supports Linux only")

    reader = SysfsReader(args.sysfs, include_ethernet=args.ethernet, strict=args.strict)

    if args.once:
        return _run_once(reader, refresh=args.refresh, sort_key=args.sort, log_level=args.log_level)

    dashboard = CursesDashboard(
        reader,
        refresh_interval=args.refresh,
        history_limit=args.history,
        sort_key=args.sort,
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        return 130
    return 0


def _run_once(
    reader: SysfsReader,
    *,
    refresh: float,
    sort_key: str,
    log_level: str,
) -> int:
    """Print one delayed rate sample using LogBar-formatted tables."""
    from logbar import LogBar

    log = LogBar.shared()
    log.setLevel(log_level)
    calculator = RateCalculator()

    try:
        calculator.update(reader.read())
        time.sleep(refresh)
        metrics = sort_metrics(calculator.update(reader.read()), sort_key)
    except Exception as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1

    terminal_width = shutil.get_terminal_size((140, 24)).columns
    formatter = LogBarTableFormatter(padding=1)
    for section in formatter.render_all(metrics, width=max(20, terminal_width - 7)):
        if section.title:
            log.info(section.title)
        for line in section.lines:
            log.info(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
