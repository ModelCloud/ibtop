from ibtop.formatting import LogBarTableFormatter
from ibtop.model import InterfaceMetrics, InterfaceStatus, IORates, InterfaceErrors, LinkErrors


def _metric() -> InterfaceMetrics:
    return InterfaceMetrics(
        status=InterfaceStatus(
            device="mlx5_0",
            port="1",
            name="mlx5_0:1",
            lid="0x1",
            link_layer="InfiniBand",
            state="4: ACTIVE",
            physical_state="5: LinkUp",
            rate="400 Gb/sec",
        ),
        io=IORates(
            rx_packets_s=10,
            rx_mb_s=1.5,
            tx_packets_s=20,
            tx_mb_s=2.5,
            uc_rx_packets_s=3,
            uc_tx_packets_s=4,
            mc_rx_packets_s=5,
            mc_tx_packets_s=6,
        ),
        errors=InterfaceErrors(1, 2, 3, 4, 5, 6, 7, 8, 9),
        link_errors=LinkErrors(10, 11, 12),
        timestamp=1.0,
    )


def test_formatter_uses_bordered_logbar_tables() -> None:
    sections = LogBarTableFormatter(padding=1).render_all([_metric()], width=120)

    assert [section.title for section in sections] == [
        "",
        "",
    ]
    ports = sections[0]
    assert any("Port" in line for line in ports.lines)
    assert any("Type" in line for line in ports.lines)
    assert any("PHY State" in line for line in ports.lines)
    assert not any("Phy State" in line for line in ports.lines)
    assert not any("Physical State" in line for line in ports.lines)
    assert not any("Name" in line for line in ports.lines)
    assert not any("Interface" in line for line in ports.lines)
    assert not any("Link Layer" in line for line in ports.lines)
    assert any("mlx5_0:1" in line for line in ports.lines)
    assert any("InfiniBand" in line for line in ports.lines)
    assert ports.lines[0].startswith("+")
    errors = sections[1]
    error_header = next(line for line in errors.lines if "Port Errors" in line)
    error_subheader = next(line for line in errors.lines if "Remote PHY" in line)
    assert "RX" in error_header and "TX" in error_header
    assert "Port Errors" in error_header
    assert not any("Port     | Symbol" in line for line in errors.lines)
    assert all(label in error_subheader for label in ("All", "Remote PHY", "Switch Relay"))
    assert error_subheader.count("Constraint") == 2
    assert "Discard" in error_subheader
    assert not any("RX Constraint" in line for line in errors.lines)
    assert not any("TX Constraint" in line for line in errors.lines)
    assert any("Recovery" in line and "Integrity" in line and "Downed" in line for line in errors.lines)
    assert not any("Const." in line for line in errors.lines)
    assert any("RX" in line and "TX" in line for line in ports.lines)
    assert any("P/s" in line and "MB/s" in line for line in ports.lines)
    assert any("Uni P/s" in line and "Multi P/s" in line for line in ports.lines)
    assert not any("Unicast" in line or "Multicast" in line for line in ports.lines)
    assert any("10" in line and "1.5" in line and "20" in line and "2.5" in line for line in ports.lines)
    assert not any("All P/s" in line or "All MB/s" in line for line in ports.lines)
    assert not any("pkt/s," in line for line in ports.lines)
    assert not any("RX Packet/s" in line for line in ports.lines)
    assert not any("UC RX Packet/s" in line for line in ports.lines)
    assert not any("Packet/s" in line or " p/s" in line for line in ports.lines)
    assert not any("per second" in line for line in ports.lines)
    assert not any("Link Error Recovery" in line for line in errors.lines)
    assert not any("Local Link Integrity" in line for line in errors.lines)


def test_formatter_aligns_shared_column_positions_across_tables() -> None:
    sections = LogBarTableFormatter(padding=1).render_all([_metric()], width=120)
    header_lines = [_header_line(section.lines) for section in sections]

    common_pipe_count = min(line.count("|") for line in header_lines)
    common_positions = [_pipe_positions(line)[:common_pipe_count] for line in header_lines]

    assert len(set(common_positions)) == 1


def _header_line(lines: list[str]) -> str:
    for line in lines:
        if "P/s" in line and "MB/s" in line:
            return line
        if "Remote PHY" in line and "Switch Relay" in line:
            return line
    return next(line for line in lines if "| Port" in line)


def _pipe_positions(line: str) -> tuple[int, ...]:
    return tuple(index for index, char in enumerate(line) if char == "|")
