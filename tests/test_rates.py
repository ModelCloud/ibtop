from ibtop.model import InterfaceSnapshot, InterfaceStatus, RateCalculator


def _status(name: str = "mlx5_0:1") -> InterfaceStatus:
    device, port = name.split(":")
    return InterfaceStatus(
        device=device,
        port=port,
        name=name,
        lid="1",
        link_layer="InfiniBand",
        state="4: ACTIVE",
        physical_state="5: LinkUp",
        rate="400 Gb/sec",
    )


def _snapshot(timestamp: float, **counters: int) -> InterfaceSnapshot:
    return InterfaceSnapshot(status=_status(), counters=counters, timestamp=timestamp)


def test_rate_calculator_converts_counter_deltas_to_rates() -> None:
    calculator = RateCalculator()
    first = _snapshot(
        10.0,
        port_rcv_packets=100,
        port_xmit_packets=200,
        port_rcv_data=1_000_000,
        port_xmit_data=2_000_000,
    )
    second = _snapshot(
        12.0,
        port_rcv_packets=300,
        port_xmit_packets=800,
        port_rcv_data=2_000_000,
        port_xmit_data=3_000_000,
    )

    initial = calculator.update([first])[0]
    assert initial.io.rx_packets_s == 0

    metrics = calculator.update([second])[0]
    assert metrics.io.rx_packets_s == 100
    assert metrics.io.tx_packets_s == 300
    assert metrics.io.rx_mb_s == 2.0
    assert metrics.io.tx_mb_s == 2.0


def test_rate_calculator_treats_counter_reset_as_zero_rate() -> None:
    calculator = RateCalculator()
    calculator.update([_snapshot(1.0, port_rcv_packets=100)])

    metrics = calculator.update([_snapshot(2.0, port_rcv_packets=5)])[0]

    assert metrics.io.rx_packets_s == 0
