"""Curses live dashboard for ibtop."""

from __future__ import annotations

import curses
import platform
import time
from datetime import datetime

from . import __version__
from .formatting import LogBarTableFormatter, TableSection
from .graph import GRAPH_HEIGHT, GraphLine, MetricHistory, render_interface_graph
from .model import SORT_KEYS, InterfaceMetrics, RateCalculator, sort_metrics
from .sysfs import NoInterfacesError, SysfsReader

RX_COLOR_PAIR = 1
TX_COLOR_PAIR = 2
BOTH_COLOR_PAIR = 3
MIN_GRAPH_HEIGHT = 3


class CursesDashboard:
    """Top-style curses dashboard for local InfiniBand metrics."""

    def __init__(
        self,
        reader: SysfsReader,
        *,
        refresh_interval: float = 1.0,
        history_limit: int = 60,
        sort_key: str = "name",
    ) -> None:
        """Prepare dashboard state around a sysfs reader."""
        self.reader = reader
        self.refresh_interval = max(0.1, float(refresh_interval))
        self.history = MetricHistory(limit=history_limit)
        self.rate_calculator = RateCalculator()
        self.formatter = LogBarTableFormatter(padding=1)
        self.sort_key = sort_key if sort_key in SORT_KEYS else "name"
        self.paused = False
        self.scroll = 0
        self._last_error = ""
        self._last_metrics: list[InterfaceMetrics] = []

    def run(self) -> None:
        """Start the curses event loop on Linux."""
        if platform.system() != "Linux":
            raise RuntimeError("ibtop currently supports Linux only")
        curses.wrapper(self._run)

    def _run(self, stdscr) -> None:
        """Drive sampling, drawing, and keyboard handling."""
        self._configure_curses(stdscr)
        next_refresh = 0.0

        while True:
            now = time.monotonic()
            if not self.paused and now >= next_refresh:
                self._sample()
                next_refresh = now + self.refresh_interval

            max_scroll = self._draw(stdscr)
            key = stdscr.getch()
            if self._handle_key(key, max_scroll):
                break
            time.sleep(0.05)

    def _sample(self) -> None:
        """Read sysfs and update sorted metrics/history state."""
        try:
            snapshots = self.reader.read()
            metrics = self.rate_calculator.update(snapshots)
            self._last_metrics = sort_metrics(metrics, self.sort_key)
            self.history.add(self._last_metrics)
            self._last_error = ""
        except NoInterfacesError as exc:
            self._last_metrics = []
            self._last_error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive UI path
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _draw(self, stdscr) -> int:
        """Draw one frame and return the maximum scroll offset."""
        height, width = stdscr.getmaxyx()
        width = max(1, width)
        visible_height = max(0, height - 2)
        body = self._body_lines(width, visible_height=visible_height)
        max_scroll = max(0, len(body) - visible_height)
        self.scroll = min(max(self.scroll, 0), max_scroll)

        stdscr.erase()
        self._add_line(stdscr, 0, self._header(width), width, curses.A_REVERSE)

        for row_index in range(visible_height):
            body_index = self.scroll + row_index
            if body_index >= len(body):
                break
            text, attr = body[body_index]
            if isinstance(text, GraphLine):
                self._add_graph_line(stdscr, row_index + 1, text, width, attr)
            else:
                self._add_line(stdscr, row_index + 1, text, width, attr)

        if height > 1:
            self._add_line(stdscr, height - 1, self._footer(max_scroll), width, curses.A_REVERSE)

        stdscr.refresh()
        return max_scroll

    def _body_lines(
        self,
        width: int,
        *,
        visible_height: int | None = None,
    ) -> list[tuple[str | GraphLine, int]]:
        """Build all body rows, sizing graphs to the visible screen height."""
        lines: list[tuple[str | GraphLine, int]] = []
        if self._last_error:
            lines.append((self._last_error, curses.A_BOLD))
            lines.append(("", curses.A_NORMAL))

        if not self._last_metrics:
            lines.append(("Waiting for InfiniBand counters...", curses.A_NORMAL))
            return lines

        table_width = max(20, width - 1)
        for section in self.formatter.render_all(self._last_metrics, width=table_width):
            self._append_section(lines, section)

        lines.append(("Throughput (MB/s over time)", curses.A_BOLD))
        graph_heights = self._graph_heights(
            visible_height=visible_height,
            fixed_rows=len(lines),
            interface_count=len(self._last_metrics),
        )
        for metric, graph_height in zip(self._last_metrics, graph_heights):
            for line in render_interface_graph(
                metric,
                self.history,
                width - 1,
                plot_height=graph_height,
            ):
                lines.append((line, curses.A_NORMAL))
        return lines

    @staticmethod
    def _graph_heights(
        *,
        visible_height: int | None,
        fixed_rows: int,
        interface_count: int,
    ) -> list[int]:
        """Allocate plot heights so graphs fill remaining body rows."""
        if interface_count <= 0:
            return []
        if visible_height is None:
            return [GRAPH_HEIGHT] * interface_count

        remaining_rows = max(0, int(visible_height) - int(fixed_rows))
        min_total_rows = MIN_GRAPH_HEIGHT + 1
        if remaining_rows < interface_count * min_total_rows:
            return [MIN_GRAPH_HEIGHT] * interface_count

        base_total_rows, extra_rows = divmod(remaining_rows, interface_count)
        return [
            max(MIN_GRAPH_HEIGHT, base_total_rows + (1 if index < extra_rows else 0) - 1)
            for index in range(interface_count)
        ]

    @staticmethod
    def _append_section(lines: list[tuple[str | GraphLine, int]], section: TableSection) -> None:
        """Append a rendered table section to body rows."""
        if section.title:
            lines.append((section.title, curses.A_BOLD))
        for line in section.lines:
            lines.append((line, curses.A_NORMAL))
        lines.append(("", curses.A_NORMAL))

    def _handle_key(self, key: int, max_scroll: int) -> bool:
        """Apply one keyboard event; return True when the UI should exit."""
        if key in (-1,):
            return False
        if key in (ord("q"), ord("Q"), 3):
            return True
        if key == ord(" "):
            self.paused = not self.paused
            return False
        if key in (ord("s"), ord("S")):
            self._cycle_sort()
            self._last_metrics = sort_metrics(self._last_metrics, self.sort_key)
            return False
        if key in (ord("e"), ord("E")):
            self.reader.include_ethernet = not self.reader.include_ethernet
            self.rate_calculator = RateCalculator()
            self._sample()
            return False
        if key == curses.KEY_DOWN:
            self.scroll = min(max_scroll, self.scroll + 1)
        elif key == curses.KEY_UP:
            self.scroll = max(0, self.scroll - 1)
        elif key == curses.KEY_NPAGE:
            self.scroll = min(max_scroll, self.scroll + 10)
        elif key == curses.KEY_PPAGE:
            self.scroll = max(0, self.scroll - 10)
        return False

    def _cycle_sort(self) -> None:
        """Advance to the next metric sort key."""
        current = SORT_KEYS.index(self.sort_key) if self.sort_key in SORT_KEYS else 0
        self.sort_key = SORT_KEYS[(current + 1) % len(SORT_KEYS)]

    def _header(self, width: int) -> str:
        """Render the fixed top status bar."""
        state = "paused" if self.paused else "live"
        ethernet = "on" if self.reader.include_ethernet else "off"
        text = (
            f" ibtop {__version__} | {state} | interfaces {len(self._last_metrics)} "
            f"| refresh {self.refresh_interval:.1f}s | sort {self.sort_key} "
            f"| ethernet {ethernet} | {datetime.now().strftime('%H:%M:%S')} "
        )
        return text[:width].ljust(width)

    def _footer(self, max_scroll: int) -> str:
        """Render the fixed bottom help and scroll bar."""
        scroll = f"scroll {self.scroll}/{max_scroll}" if max_scroll else "scroll 0/0"
        return (
            " q quit | space pause | s sort | e ethernet | arrows/page scroll | "
            f"{scroll} "
        )

    @staticmethod
    def _configure_curses(stdscr) -> None:
        """Configure curses input mode and color pairs."""
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.nodelay(True)
        stdscr.keypad(True)
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        try:
            if curses.has_colors():
                curses.start_color()
                curses.init_pair(RX_COLOR_PAIR, curses.COLOR_CYAN, -1)
                curses.init_pair(TX_COLOR_PAIR, curses.COLOR_GREEN, -1)
                curses.init_pair(BOTH_COLOR_PAIR, curses.COLOR_YELLOW, -1)
        except curses.error:
            pass

    @staticmethod
    def _add_line(stdscr, y: int, text: str, width: int, attr: int) -> None:
        """Draw a plain row while tolerating terminal resize races."""
        try:
            stdscr.addnstr(y, 0, text.ljust(width), max(0, width - 1), attr)
        except curses.error:
            pass

    @classmethod
    def _add_graph_line(cls, stdscr, y: int, line: GraphLine, width: int, attr: int) -> None:
        """Draw a styled graph row segment by segment."""
        try:
            stdscr.addnstr(y, 0, " " * width, max(0, width - 1), attr)
        except curses.error:
            return

        x = 0
        for segment in line.segments:
            if x >= width - 1:
                break
            text = segment.text[: max(0, width - 1 - x)]
            if not text:
                continue
            try:
                stdscr.addnstr(y, x, text, len(text), cls._graph_attr(segment.style, attr))
            except curses.error:
                pass
            x += len(text)

    @staticmethod
    def _graph_attr(style: str | None, base_attr: int) -> int:
        """Map graph style names to curses attributes."""
        if style == "rx":
            return base_attr | curses.color_pair(RX_COLOR_PAIR) | curses.A_BOLD
        if style == "tx":
            return base_attr | curses.color_pair(TX_COLOR_PAIR) | curses.A_BOLD
        if style == "both":
            return base_attr | curses.color_pair(BOTH_COLOR_PAIR) | curses.A_BOLD
        return base_attr
