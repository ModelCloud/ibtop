from pathlib import Path

import pytest

from ibtop.sysfs import NoInterfacesError, SysfsReader


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _port(root: Path, device: str, port: str, *, link_layer: str = "InfiniBand") -> Path:
    port_path = root / device / "ports" / port
    _write(port_path / "lid", "0x1\n")
    _write(port_path / "link_layer", f"{link_layer}\n")
    _write(port_path / "state", "4: ACTIVE\n")
    _write(port_path / "phys_state", "5: LinkUp\n")
    _write(port_path / "rate", "400 Gb/sec\n")
    return port_path


def test_sysfs_reader_reads_status_and_counter_fallbacks(tmp_path: Path) -> None:
    port_path = _port(tmp_path, "mlx5_0", "1")
    _write(port_path / "counters" / "port_rcv_packets_64", "42\n")
    _write(port_path / "counters" / "port_xmit_packets", "7\n")
    _write(port_path / "counters" / "port_rcv_data", "10\n")

    snapshots = SysfsReader(tmp_path).read()

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.status.name == "mlx5_0:1"
    assert snapshot.status.link_layer == "InfiniBand"
    assert snapshot.counters["port_rcv_packets"] == 42
    assert snapshot.counters["port_xmit_packets"] == 7
    assert snapshot.counters["port_rcv_data"] == 10


def test_sysfs_reader_filters_ethernet_by_default(tmp_path: Path) -> None:
    _port(tmp_path, "mlx5_0", "1", link_layer="Ethernet")

    with pytest.raises(NoInterfacesError):
        SysfsReader(tmp_path).read()

    snapshots = SysfsReader(tmp_path, include_ethernet=True).read()
    assert snapshots[0].status.link_layer == "Ethernet"
