"""LogBar-backed table layout and rendering helpers."""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .model import InterfaceMetrics

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

PORT_COLUMNS: tuple[object, ...] = (
    "Port",
    "LID",
    "Type",
    "State",
    "PHY State",
    "Rate",
    {"label": "RX", "span": 4},
    {"label": "TX", "span": 4},
)
PORT_SUBCOLUMNS = (
    "",
    "",
    "",
    "",
    "",
    "",
    "P/s",
    "MB/s",
    "Uni P/s",
    "Multi P/s",
    "P/s",
    "MB/s",
    "Uni P/s",
    "Multi P/s",
)
ERROR_COLUMNS: tuple[object, ...] = (
    "Port Errors",
    "Symbol",
    {"label": "RX", "span": 4},
    {"label": "TX", "span": 2},
    "Buffer Overrun",
    "VL15 Dropped",
    "Recovery",
    "Integrity",
    "Downed",
)
ERROR_SUBCOLUMNS = (
    "",
    "",
    "All",
    "Remote PHY",
    "Switch Relay",
    "Constraint",
    "Constraint",
    "Discard",
    "",
    "",
    "",
    "",
    "",
)


@dataclass(frozen=True)
class TableSection:
    """Rendered table block ready for curses or one-shot logging."""

    title: str
    lines: list[str]


@dataclass(frozen=True)
class _TableData:
    """Structured table input before LogBar computes column widths."""

    title: str
    columns: tuple[object, ...]
    rows: tuple[tuple[str, ...], ...]
    subcolumns: tuple[str, ...] = ()


class LogBarTableFormatter:
    """Render ibtop tables through LogBar's column formatter."""

    def __init__(self, *, padding: int = 1) -> None:
        """Create a formatter with LogBar-compatible cell padding."""
        self.padding = max(0, int(padding))

    def render_all(self, metrics: Iterable[InterfaceMetrics], *, width: int) -> list[TableSection]:
        """Render all dashboard tables with shared base-column alignment."""
        items = list(metrics)
        tables = (
            self._ports_data(items),
            self._errors_data(items),
        )
        widths = self._shared_widths(tables)
        return [self._render_table(self._pad_table(table, widths), width=width) for table in tables]

    def render_ports(
        self,
        metrics: Sequence[InterfaceMetrics],
        *,
        width: int,
    ) -> TableSection:
        """Render the status and I/O table."""
        return self._render_table(self._ports_data(metrics), width=width)

    def _ports_data(self, metrics: Sequence[InterfaceMetrics]) -> _TableData:
        """Build status and I/O rows for each port."""
        rows = [
            (
                item.name,
                item.status.lid,
                item.status.link_layer,
                item.status.state,
                item.status.physical_state,
                item.status.rate,
                _rate(item.io.rx_packets_s),
                _mb(item.io.rx_mb_s),
                _rate(item.io.uc_rx_packets_s),
                _rate(item.io.mc_rx_packets_s),
                _rate(item.io.tx_packets_s),
                _mb(item.io.tx_mb_s),
                _rate(item.io.uc_tx_packets_s),
                _rate(item.io.mc_tx_packets_s),
            )
            for item in metrics
        ]
        return _TableData(
            title="",
            columns=PORT_COLUMNS,
            subcolumns=PORT_SUBCOLUMNS,
            rows=tuple(tuple(str(value) for value in row) for row in rows),
        )

    def render_errors(
        self,
        metrics: Sequence[InterfaceMetrics],
        *,
        width: int,
    ) -> TableSection:
        """Render the grouped interface and link error table."""
        return self._render_table(self._errors_data(metrics), width=width)

    def _errors_data(self, metrics: Sequence[InterfaceMetrics]) -> _TableData:
        """Build cumulative error rows for each port."""
        rows = [
            (
                item.name,
                _count(item.errors.symbol),
                _count(item.errors.rx),
                _count(item.errors.rx_remote_physical),
                _count(item.errors.rx_switch_relay),
                _count(item.errors.rx_constraint),
                _count(item.errors.tx_constraint),
                _count(item.errors.buffer_overrun),
                _count(item.errors.tx_discard),
                _count(item.errors.vl15_dropped),
                _count(item.link_errors.link_error_recovery),
                _count(item.link_errors.local_link_integrity),
                _count(item.link_errors.link_downed),
            )
            for item in metrics
        ]
        return _TableData(
            title="",
            columns=ERROR_COLUMNS,
            subcolumns=ERROR_SUBCOLUMNS,
            rows=tuple(tuple(str(value) for value in row) for row in rows),
        )

    def _render_table(
        self,
        table: _TableData,
        *,
        width: int,
    ) -> TableSection:
        """Render a padded table through LogBar and strip terminal control codes."""
        from logbar import LogBar

        del width

        log = LogBar(f"ibtop.table.{id(table)}")
        printer = log.columns(cols=table.columns, padding=self.padding)

        if table.subcolumns:
            printer.info.simulate(*table.subcolumns)
        for row in table.rows:
            printer.info.simulate(*row)

        header = self._capture(printer.info.header)
        border = self._border(printer.widths, printer.padding)
        lines = [border, header]
        if table.subcolumns:
            lines.append(self._capture(lambda: printer.info(*table.subcolumns)))
        lines.append(border)
        for row in table.rows:
            lines.append(self._capture(lambda row=row: printer.info(*row)))
        lines.append(border)
        return TableSection(title=table.title, lines=[_clean(line) for line in lines if line])

    @staticmethod
    def _shared_widths(tables: Sequence[_TableData]) -> list[int]:
        """Compute per-slot widths shared by all rendered tables."""
        max_columns = max((_slot_count(table) for table in tables), default=0)
        widths = [0] * max_columns
        for table in tables:
            slot = 0
            for column in table.columns:
                label, span = _column_label_and_span(column)
                if span == 1 and slot < len(widths):
                    widths[slot] = max(widths[slot], len(label))
                slot += span
            for index, column in enumerate(table.subcolumns):
                widths[index] = max(widths[index], len(column))
            for row in table.rows:
                for index, value in enumerate(row):
                    widths[index] = max(widths[index], len(value))
        return widths

    @staticmethod
    def _pad_table(table: _TableData, widths: Sequence[int]) -> _TableData:
        """Pad table data to shared widths before handing it to LogBar."""
        padded_columns = []
        slot = 0
        for column in table.columns:
            padded_columns.append(_pad_column(column, widths, slot))
            _, span = _column_label_and_span(column)
            slot += span
        columns = tuple(padded_columns)
        subcolumns = tuple(
            _pad(value, widths[index]) for index, value in enumerate(table.subcolumns)
        )
        rows = tuple(
            tuple(_pad(value, widths[index]) for index, value in enumerate(row))
            for row in table.rows
        )
        return _TableData(title=table.title, columns=columns, subcolumns=subcolumns, rows=rows)

    def _capture(self, func) -> str:
        """Capture LogBar's stdout-based renderer as a string."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            value = func()
        return str(value)

    @staticmethod
    def _border(widths: Sequence[int], padding: int) -> str:
        """Build a border line matching LogBar's computed widths."""
        segments = ["-" * (max(1, width) + (padding * 2)) for width in widths]
        return "+" + "+".join(segments) + "+"


def _clean(value: str) -> str:
    """Remove ANSI sequences and carriage returns from captured LogBar output."""
    return ANSI_RE.sub("", value).replace("\r", "")


def _pad(value: object, width: int) -> str:
    """Left-pad a cell label/value to a shared width."""
    return str(value).ljust(max(0, width))


def _pad_column(column: object, widths: Sequence[int], slot: int) -> object:
    """Pad simple columns while preserving LogBar span-column dictionaries."""
    label, span = _column_label_and_span(column)
    if span != 1:
        if isinstance(column, dict):
            copied = dict(column)
            copied["label"] = label
            return copied
        return column

    width = widths[slot] if slot < len(widths) else len(label)
    if isinstance(column, dict):
        copied = dict(column)
        copied["label"] = _pad(label, width)
        return copied
    return _pad(label, width)


def _column_label_and_span(column: object) -> tuple[str, int]:
    """Normalize string or dictionary column declarations."""
    if isinstance(column, dict):
        return str(column.get("label") or column.get("name") or ""), max(1, int(column.get("span", 1)))
    return str(column), 1


def _slot_count(table: _TableData) -> int:
    """Return the concrete column-slot count after expanding spans."""
    return sum(_column_label_and_span(column)[1] for column in table.columns)


def _rate(value: float) -> str:
    """Format packet-rate values for table cells."""
    return f"{value:,.0f}"


def _mb(value: float) -> str:
    """Format MB/s values for table cells."""
    return f"{value:,.1f}"


def _count(value: int) -> str:
    """Format cumulative integer counters for table cells."""
    return f"{int(value):,}"
