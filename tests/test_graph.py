from ibtop.graph import GRAPH_HEIGHT, MetricHistory, dual_line_plot, line_plot, render_interface_graph, sparkline
from ibtop.model import InterfaceMetrics, InterfaceStatus, IORates, InterfaceErrors, LinkErrors


def _metric(rx: float, tx: float) -> InterfaceMetrics:
    return InterfaceMetrics(
        status=InterfaceStatus(
            device="mlx5_0",
            port="1",
            name="mlx5_0:1",
            lid="1",
            link_layer="InfiniBand",
            state="4: ACTIVE",
            physical_state="5: LinkUp",
            rate="400 Gb/sec",
        ),
        io=IORates(
            rx_packets_s=rx * 100,
            rx_mb_s=rx,
            tx_packets_s=tx * 100,
            tx_mb_s=tx,
            uc_rx_packets_s=0,
            uc_tx_packets_s=0,
            mc_rx_packets_s=0,
            mc_tx_packets_s=0,
        ),
        errors=InterfaceErrors(0, 0, 0, 0, 0, 0, 0, 0, 0),
        link_errors=LinkErrors(0, 0, 0),
        timestamp=1.0,
    )


def test_sparkline_is_fixed_width() -> None:
    assert len(sparkline([0, 1, 2, 3], 10)) == 10
    assert sparkline([], 4) == "    "


def test_interface_graph_includes_current_rx_and_tx_values() -> None:
    history = MetricHistory(limit=4)
    history.add([_metric(1.0, 2.0)])
    history.add([_metric(3.0, 4.0)])

    lines = render_interface_graph(_metric(3.0, 4.0), history, 100)
    text = "\n".join(line.text for line in lines)
    styles = {segment.style for line in lines for segment in line.segments}
    title_segments = lines[0].segments

    assert "mlx5_0:1" in text
    assert "MB/s" in text
    assert "P/s" in text
    assert "Pkt/s" not in text
    assert "RX 3.0" in text
    assert "TX 4.0" in text
    assert "RX 300" in text
    assert "TX 400" in text
    assert "400 │" in text
    assert "RX TX" not in lines[0].text
    assert any(segment.style == "rx" and "RX 3.0" in segment.text for segment in title_segments)
    assert any(segment.style == "tx" and "TX 4.0" in segment.text for segment in title_segments)
    assert any(segment.style == "rx" and "RX 300" in segment.text for segment in title_segments)
    assert any(segment.style == "tx" and "TX 400" in segment.text for segment in title_segments)
    assert any("│" in line.text for line in lines)
    assert "rx" in styles
    assert "tx" in styles
    assert sum(1 for line in lines if " │ " in line.text) == GRAPH_HEIGHT
    assert any("4.0 │ " in line.text for line in lines)
    assert any("2.0 │ " in line.text for line in lines)
    assert any("0.0 │ " in line.text for line in lines)


def test_interface_graph_accepts_dynamic_plot_height() -> None:
    history = MetricHistory(limit=4)
    history.add([_metric(1.0, 2.0)])
    history.add([_metric(3.0, 4.0)])

    lines = render_interface_graph(_metric(3.0, 4.0), history, 100, plot_height=14)

    assert len(lines) == 15
    assert sum(1 for line in lines if " │ " in line.text) == 14


def test_line_plot_uses_connected_line_glyphs() -> None:
    lines = line_plot([0, 1, 3, 1, 0], 5, height=3)
    text = "\n".join(lines)
    line_glyphs = {"─", "│", "┌", "┐", "└", "┘", "┬", "┴", "╶", "╴"}

    assert len(lines) == 3
    assert all(len(line) == 5 for line in lines)
    assert any(glyph in text for glyph in line_glyphs)
    assert "/" not in text
    assert "\\" not in text


def test_line_plot_interpolates_large_vertical_changes_across_columns() -> None:
    lines = line_plot([0, 100], 20, height=20)
    populated_cells_by_column = [
        sum(1 for line in lines if line[column] != " ")
        for column in range(20)
    ]

    assert max(populated_cells_by_column) <= 2


def test_line_plot_avoids_dangling_cap_glyphs() -> None:
    lines = line_plot([0, 100, 0, 60, 0], 30, height=20)
    text = "\n".join(lines)

    assert not any(glyph in text for glyph in "╷╵╶╴")


def test_dual_line_plot_merges_rx_and_tx_into_one_colored_graph() -> None:
    lines = dual_line_plot([0, 1, 3, 1, 0], [3, 2, 1, 2, 3], 5, height=4)
    text = "\n".join(line.text for line in lines)
    styles = {segment.style for line in lines for segment in line.segments}

    assert len(lines) == 4
    assert all(len(line.text) == 5 for line in lines)
    assert any(glyph in text for glyph in {"─", "│", "┌", "┐", "└", "┘", "┬", "┴", "┼"})
    assert "rx" in styles
    assert "tx" in styles


def test_dual_line_plot_omits_flat_zero_series() -> None:
    lines = dual_line_plot([0, 0, 0, 0], [0.2, 1.0, 0.2, 0.4], 20, height=5)
    styles = {segment.style for line in lines for segment in line.segments}

    assert "rx" not in styles
    assert "tx" in styles
    assert "both" not in styles


def test_graph_labels_small_nonzero_values_with_precision() -> None:
    history = MetricHistory(limit=4)
    history.add([_metric(0.0, 0.002)])
    history.add([_metric(0.0, 0.006)])
    history.add([_metric(0.0, 0.004)])

    lines = render_interface_graph(_metric(0.0, 0.004), history, 80)
    text = "\n".join(line.text for line in lines)

    assert "TX 0.0040" in text
    assert "0.0060 │" in text
