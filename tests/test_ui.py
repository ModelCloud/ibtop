from ibtop.graph import GRAPH_HEIGHT, GraphLine
from ibtop.model import InterfaceErrors, InterfaceMetrics, InterfaceStatus, IORates, LinkErrors
from ibtop.ui import CursesDashboard, MIN_GRAPH_HEIGHT


def _metric(name: str, rx: float, tx: float) -> InterfaceMetrics:
    return InterfaceMetrics(
        status=InterfaceStatus(
            device=name.split(":", 1)[0],
            port=name.split(":", 1)[1],
            name=name,
            lid="0x1",
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


def test_body_lines_expand_graphs_to_fill_visible_height() -> None:
    dashboard = CursesDashboard(reader=object())
    dashboard._last_metrics = [
        _metric("mlx5_0:1", 1.0, 2.0),
        _metric("mlx5_1:1", 3.0, 4.0),
    ]
    dashboard.history.add(dashboard._last_metrics)

    lines = dashboard._body_lines(140, visible_height=50)
    graph_lines = [text for text, _ in lines if isinstance(text, GraphLine)]

    assert len(lines) == 50
    assert len(graph_lines) > len(dashboard._last_metrics) * (GRAPH_HEIGHT + 1)


def test_graph_height_allocation_keeps_minimum_when_space_is_tight() -> None:
    assert CursesDashboard._graph_heights(
        visible_height=4,
        fixed_rows=3,
        interface_count=2,
    ) == [MIN_GRAPH_HEIGHT, MIN_GRAPH_HEIGHT]
