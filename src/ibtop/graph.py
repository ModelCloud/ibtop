"""Terminal graph rendering for per-port traffic history."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Iterable

from .model import InterfaceMetrics

GRAPH_HEIGHT = 9
ZERO_LINE_EPSILON = 0.0


@dataclass(frozen=True)
class GraphPoint:
    """One historical sample used by both graph panels."""

    rx_mb_s: float
    tx_mb_s: float
    rx_packets_s: float
    tx_packets_s: float


@dataclass(frozen=True)
class GraphSegment:
    """A styled run of text; style names map to curses color pairs."""

    text: str
    style: str | None = None


@dataclass(frozen=True)
class GraphLine:
    """A renderable graph row made of styled text segments."""

    segments: tuple[GraphSegment, ...]

    @property
    def text(self) -> str:
        """Return the unstyled line text."""
        return "".join(segment.text for segment in self.segments)

    def __str__(self) -> str:
        """Return unstyled text for logs and tests."""
        return self.text


@dataclass
class _GraphCell:
    """A plotted cell with line-connection bits and optional style."""

    mask: int = 0
    style: str | None = None


UP = 1
DOWN = 2
LEFT = 4
RIGHT = 8
POINT = 16

GLYPHS = {
    0: " ",
    POINT: "•",
    UP: "│",
    DOWN: "│",
    LEFT: "─",
    RIGHT: "─",
    LEFT | RIGHT: "─",
    UP | DOWN: "│",
    DOWN | RIGHT: "┌",
    DOWN | LEFT: "┐",
    UP | RIGHT: "└",
    UP | LEFT: "┘",
    LEFT | RIGHT | DOWN: "┬",
    LEFT | RIGHT | UP: "┴",
    UP | DOWN | RIGHT: "├",
    UP | DOWN | LEFT: "┤",
    UP | DOWN | LEFT | RIGHT: "┼",
}


class MetricHistory:
    """Bounded per-interface metric history for sparkline graphs."""

    def __init__(self, limit: int = 60) -> None:
        """Create per-port history buffers with a fixed sample limit."""
        self.limit = max(2, int(limit))
        self._points: dict[str, Deque[GraphPoint]] = defaultdict(
            lambda: deque(maxlen=self.limit)
        )

    def add(self, metrics: Iterable[InterfaceMetrics]) -> None:
        """Append the latest metrics for every sampled port."""
        for item in metrics:
            self._points[item.name].append(
                GraphPoint(
                    rx_mb_s=item.io.rx_mb_s,
                    tx_mb_s=item.io.tx_mb_s,
                    rx_packets_s=item.io.rx_packets_s,
                    tx_packets_s=item.io.tx_packets_s,
                )
            )

    def points(self, name: str) -> list[GraphPoint]:
        """Return a copy of the stored points for one port."""
        return list(self._points.get(name, ()))


def sparkline(values: Iterable[float], width: int, charset: str = " .:-=+*#%@") -> str:
    """Render a fixed-width ASCII sparkline for simple non-curses output."""
    width = max(0, int(width))
    if width == 0:
        return ""

    series = [max(0.0, float(value)) for value in values]
    if len(series) > width:
        series = series[-width:]
    elif len(series) < width:
        series = [0.0] * (width - len(series)) + series

    maximum = max(series) if series else 0.0
    if maximum <= 0.0:
        return " " * width

    levels = len(charset) - 1
    return "".join(charset[round((value / maximum) * levels)] for value in series)


def render_interface_graph(
    metric: InterfaceMetrics,
    history: MetricHistory,
    width: int,
    *,
    plot_height: int = GRAPH_HEIGHT,
) -> list[GraphLine]:
    """Render one port as side-by-side MB/s and P/s panels."""
    width = max(50, int(width))
    plot_height = max(1, int(plot_height))
    points = history.points(metric.name)
    gap = "  "
    left_width = max(24, (width - len(gap)) // 2)
    right_width = max(24, width - len(gap) - left_width)

    mb_panel = _render_panel(
        title=f"{metric.name} MB/s",
        rx_title=f" RX {_format_rate_value(metric.io.rx_mb_s)}",
        tx_title=f" TX {_format_rate_value(metric.io.tx_mb_s)}",
        rx_values=[point.rx_mb_s for point in points],
        tx_values=[point.tx_mb_s for point in points],
        width=left_width,
        height=plot_height,
        value_formatter=_format_rate_value,
    )
    packet_panel = _render_panel(
        title="P/s",
        rx_title=f" RX {_format_count_rate_value(metric.io.rx_packets_s)}",
        tx_title=f" TX {_format_count_rate_value(metric.io.tx_packets_s)}",
        rx_values=[point.rx_packets_s for point in points],
        tx_values=[point.tx_packets_s for point in points],
        width=right_width,
        height=plot_height,
        value_formatter=_format_count_axis_value,
    )

    return [
        _join_graph_lines(left, right, gap)
        for left, right in zip(mb_panel, packet_panel)
    ]


def _render_panel(
    *,
    title: str,
    rx_title: str,
    tx_title: str,
    rx_values: list[float],
    tx_values: list[float],
    width: int,
    height: int,
    value_formatter,
) -> list[GraphLine]:
    """Render one graph panel, including title, Y-axis labels, and plot rows."""
    width = max(24, int(width))
    height = max(1, int(height))
    title_width = max(0, width - len(rx_title) - len(tx_title))
    title_text = title[:title_width].rstrip()
    y_labels = _y_axis_labels(rx_values, tx_values, height, value_formatter)
    y_axis_width = max(len(label) for label in y_labels)
    graph_width = max(8, width - y_axis_width - 3)
    plot = dual_line_plot(rx_values, tx_values, graph_width, height=height)
    return [
        _title_line(
            (
                GraphSegment(title_text),
                GraphSegment(rx_title, "rx"),
                GraphSegment(tx_title, "tx"),
            ),
            width,
        ),
        *[
            _prefix_graph_line(line, f"{label.rjust(y_axis_width)} │ ")
            for label, line in zip(y_labels, plot)
        ],
    ]


def _title_line(segments: Iterable[GraphSegment], width: int) -> GraphLine:
    """Fit styled title segments into a fixed-width graph header."""
    remaining = max(0, int(width))
    rendered: list[GraphSegment] = []
    for segment in segments:
        if remaining <= 0:
            break
        text = segment.text[:remaining]
        if text:
            rendered.append(GraphSegment(text, segment.style))
            remaining -= len(text)
    if remaining > 0:
        rendered.append(GraphSegment(" " * remaining))
    return GraphLine(tuple(rendered))


def _join_graph_lines(left: GraphLine, right: GraphLine, gap: str) -> GraphLine:
    """Join two graph panels without losing segment color styles."""
    return GraphLine((*left.segments, GraphSegment(gap), *right.segments))


def dual_line_plot(
    rx_values: Iterable[float],
    tx_values: Iterable[float],
    width: int,
    *,
    height: int = 4,
) -> list[GraphLine]:
    """Render RX and TX series into one colored connected-line plot."""
    width = max(1, int(width))
    height = max(1, int(height))
    rx_series = _normalize_series(rx_values, width)
    tx_series = _normalize_series(tx_values, width)
    rx_active = _series_is_plottable(rx_series)
    tx_active = _series_is_plottable(tx_series)
    real_values = []
    if rx_active:
        real_values.extend(rx_series)
    if tx_active:
        real_values.extend(tx_series)
    maximum = max(real_values, default=0.0)

    grid = [[_GraphCell() for _ in range(width)] for _ in range(height)]
    if maximum <= 0.0:
        return [_segments_from_cells(row) for row in grid]

    if rx_active:
        _draw_series(grid, _to_y_points(rx_series, maximum, height), "rx")
    if tx_active:
        _draw_series(grid, _to_y_points(tx_series, maximum, height), "tx")
    return [_segments_from_cells(row) for row in grid]


def line_plot(values: Iterable[float], width: int, *, height: int = 3) -> list[str]:
    """Render a compact fixed-width line graph using connected line glyphs."""

    width = max(1, int(width))
    height = max(1, int(height))
    series = _normalize_series(values, width)
    maximum = max(series, default=0.0)
    grid = [[_GraphCell() for _ in range(width)] for _ in range(height)]

    if maximum > 0.0:
        _draw_series(grid, _to_y_points(series, maximum, height), None)

    return [line.text for line in (_segments_from_cells(row) for row in grid)]


def _y_axis_labels(
    rx_values: Iterable[float],
    tx_values: Iterable[float],
    height: int,
    value_formatter=None,
) -> list[str]:
    """Return sparse top/middle/bottom Y-axis labels for a panel."""
    if value_formatter is None:
        value_formatter = _format_rate_value
    height = max(1, int(height))
    values = [max(0.0, float(value)) for value in [*rx_values, *tx_values]]
    maximum = max(values, default=0.0)
    labels = [""] * height
    marks = (
        (0, maximum),
        (round((height - 1) * 0.5), maximum * 0.5),
        (height - 1, 0.0),
    )
    for row, value in marks:
        labels[row] = value_formatter(value)
    return labels


def _format_rate_value(value: float) -> str:
    """Format throughput values for compact title and axis labels."""
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    if value >= 0.1:
        return f"{value:.1f}"
    if value >= 0.01:
        return f"{value:.3f}"
    if value > 0:
        return f"{value:.4f}"
    return f"{value:.1f}"


def _format_count_rate_value(value: float) -> str:
    """Format packet-rate values for compact graph titles."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.0f}K"
    if value >= 1000:
        return f"{value / 1_000:.1f}K"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    if value > 0:
        return f"{value:.2f}"
    return "0"


def _format_count_axis_value(value: float) -> str:
    """Format packet-rate values for Y-axis labels."""
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    if value > 0:
        return f"{value:.2f}"
    return "0"


def _normalize_series(values: Iterable[float], width: int) -> list[float]:
    """Clamp negatives to zero and downsample long histories to graph width."""
    series = [max(0.0, float(value)) for value in values]
    if not series:
        return []
    if len(series) <= width:
        return series[-width:]

    scaled: list[float] = []
    for column in range(width):
        start = int((column / width) * len(series))
        end = int(((column + 1) / width) * len(series))
        bucket = series[start : max(start + 1, end)]
        scaled.append(sum(bucket) / len(bucket))
    return scaled


def _series_is_plottable(series: Iterable[float]) -> bool:
    """Return whether a series should draw a line instead of an empty baseline."""
    return max(series, default=0.0) > ZERO_LINE_EPSILON


def _to_y_points(series: Iterable[float], maximum: float, height: int) -> list[int]:
    """Map values into integer row coordinates for the plot grid."""
    levels = height - 1
    return [levels - round((value / maximum) * levels) for value in series]


def _draw_series(
    grid: list[list[_GraphCell]],
    y_points: list[int],
    style: str | None,
) -> None:
    """Draw one styled series into a mutable cell grid."""
    points = _position_points(y_points, _grid_width(grid))
    if not points:
        return
    if len(points) == 1:
        x, y = points[0]
        _put_mask(grid, x, y, POINT, style)
        return

    _draw_path(grid, _interpolated_path(points), style)


def _position_points(y_points: list[int], width: int) -> list[tuple[int, int]]:
    """Spread sample Y coordinates across the available graph columns."""
    if not y_points or width <= 0:
        return []
    if len(y_points) == 1:
        return [(width - 1, y_points[0])]

    last_point = len(y_points) - 1
    last_column = max(1, width - 1)
    positioned: list[tuple[int, int]] = []
    for index, y in enumerate(y_points):
        x = round((index / last_point) * last_column)
        if positioned and positioned[-1][0] == x:
            positioned[-1] = (x, y)
        else:
            positioned.append((x, y))
    return positioned


def _grid_width(grid: list[list[_GraphCell]]) -> int:
    """Return grid width without assuming the grid has rows."""
    if not grid:
        return 0
    return len(grid[0])


def _interpolated_path(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Interpolate sparse sample points into a connected terminal path."""
    if not points:
        return []

    path = [points[0]]
    for start, end in zip(points, points[1:]):
        for point in _segment_points(start, end)[1:]:
            if point != path[-1]:
                path.append(point)
    return path


def _segment_points(
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    """Return rounded points along a straight segment."""
    x0, y0 = start
    x1, y1 = end
    steps = max(abs(x1 - x0), abs(y1 - y0))
    if steps <= 0:
        return [start]

    points: list[tuple[int, int]] = []
    for step in range(steps + 1):
        ratio = step / steps
        x = round(x0 + ((x1 - x0) * ratio))
        y = round(y0 + ((y1 - y0) * ratio))
        point = (x, y)
        if not points or point != points[-1]:
            points.append(point)
    return points


def _draw_path(
    grid: list[list[_GraphCell]],
    path: list[tuple[int, int]],
    style: str | None,
) -> None:
    """Draw an interpolated path into the grid."""
    if not path:
        return
    if len(path) == 1:
        x, y = path[0]
        _put_mask(grid, x, y, POINT, style)
        return

    current = path[0]
    for target in path[1:]:
        current = _connect_cells(grid, current, target, style)


def _connect_cells(
    grid: list[list[_GraphCell]],
    current: tuple[int, int],
    target: tuple[int, int],
    style: str | None,
) -> tuple[int, int]:
    """Connect two path points using adjacent terminal cells."""
    x, y = current
    target_x, target_y = target

    while (x, y) != (target_x, target_y):
        dx = _sign(target_x - x)
        dy = _sign(target_y - y)
        if dx and (not dy or abs(target_x - x) >= abs(target_y - y)):
            next_x, next_y = x + dx, y
        else:
            next_x, next_y = x, y + dy
        _connect_adjacent(grid, (x, y), (next_x, next_y), style)
        x, y = next_x, next_y
    return x, y


def _connect_adjacent(
    grid: list[list[_GraphCell]],
    start: tuple[int, int],
    end: tuple[int, int],
    style: str | None,
) -> None:
    """Set masks on two neighboring cells so glyphs connect visually."""
    x0, y0 = start
    x1, y1 = end
    if x1 > x0:
        _put_mask(grid, x0, y0, RIGHT, style)
        _put_mask(grid, x1, y1, LEFT, style)
        return
    if x1 < x0:
        _put_mask(grid, x0, y0, LEFT, style)
        _put_mask(grid, x1, y1, RIGHT, style)
        return
    if y1 > y0:
        _put_mask(grid, x0, y0, DOWN, style)
        _put_mask(grid, x1, y1, UP, style)
        return
    if y1 < y0:
        _put_mask(grid, x0, y0, UP, style)
        _put_mask(grid, x1, y1, DOWN, style)


def _sign(value: int) -> int:
    """Return the direction of an integer delta."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _put_mask(
    grid: list[list[_GraphCell]],
    x: int,
    y: int,
    mask: int,
    style: str | None,
) -> None:
    """Merge a line segment mask and style into a grid cell."""
    if not grid or not (0 <= y < len(grid)) or not (0 <= x < len(grid[y])):
        return

    cell = grid[y][x]
    if cell.style is None:
        cell.mask = _merge_masks(cell.mask, mask)
        cell.style = style
        return
    if cell.style == style:
        cell.mask = _merge_masks(cell.mask, mask)
        return
    cell.mask = _merge_masks(cell.mask, mask)
    cell.style = "both"


def _merge_masks(existing: int, incoming: int) -> int:
    """Combine connection bits while replacing standalone point markers."""
    if existing == POINT:
        existing = 0
    if incoming == POINT and existing:
        incoming = 0
    return existing | incoming


def _segments_from_cells(cells: list[_GraphCell]) -> GraphLine:
    """Collapse adjacent cells with the same style into text segments."""
    if not cells:
        return GraphLine(())

    segments: list[GraphSegment] = []
    current_style = cells[0].style
    current_text = [_cell_char(cells[0])]
    for cell in cells[1:]:
        if cell.style == current_style:
            current_text.append(_cell_char(cell))
            continue
        segments.append(GraphSegment("".join(current_text), current_style))
        current_style = cell.style
        current_text = [_cell_char(cell)]
    segments.append(GraphSegment("".join(current_text), current_style))
    return GraphLine(tuple(segments))


def _cell_char(cell: _GraphCell) -> str:
    """Map a cell's connection mask to a box-drawing glyph."""
    return GLYPHS.get(cell.mask, "┼")


def _prefix_graph_line(line: GraphLine, prefix: str) -> GraphLine:
    """Attach an unstyled axis prefix to a styled graph row."""
    return GraphLine((GraphSegment(prefix), *line.segments))
