"""Typed metric model and rate conversion for InfiniBand sysfs samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

BYTES_PER_MB = 1_000_000
INFINIBAND_DATA_COUNTER_BYTES = 4
SORT_KEYS = ("name", "rx", "tx", "total", "errors")


@dataclass(frozen=True)
class InterfaceStatus:
    """Static port identity and link-status fields read from sysfs."""

    device: str
    port: str
    name: str
    lid: str
    link_layer: str
    state: str
    physical_state: str
    rate: str


@dataclass(frozen=True)
class InterfaceSnapshot:
    """Raw counter sample for one port at a monotonic timestamp."""

    status: InterfaceStatus
    counters: Mapping[str, int]
    timestamp: float


@dataclass(frozen=True)
class IORates:
    """Per-second traffic rates derived from two counter snapshots."""

    rx_packets_s: float
    rx_mb_s: float
    tx_packets_s: float
    tx_mb_s: float
    uc_rx_packets_s: float
    uc_tx_packets_s: float
    mc_rx_packets_s: float
    mc_tx_packets_s: float


@dataclass(frozen=True)
class InterfaceErrors:
    """Cumulative per-port error counters from sysfs."""

    symbol: int
    rx: int
    rx_remote_physical: int
    rx_switch_relay: int
    rx_constraint: int
    tx_constraint: int
    buffer_overrun: int
    tx_discard: int
    vl15_dropped: int

    @property
    def total(self) -> int:
        """Return a coarse aggregate for error-based sorting."""
        return sum(
            (
                self.symbol,
                self.rx,
                self.rx_remote_physical,
                self.rx_switch_relay,
                self.rx_constraint,
                self.tx_constraint,
                self.buffer_overrun,
                self.tx_discard,
                self.vl15_dropped,
            )
        )


@dataclass(frozen=True)
class LinkErrors:
    """Cumulative link-state error counters from sysfs."""

    link_error_recovery: int
    local_link_integrity: int
    link_downed: int

    @property
    def total(self) -> int:
        """Return a coarse aggregate for error-based sorting."""
        return sum((self.link_error_recovery, self.local_link_integrity, self.link_downed))


@dataclass(frozen=True)
class InterfaceMetrics:
    """Display-ready status, rates, and error counters for one port."""

    status: InterfaceStatus
    io: IORates
    errors: InterfaceErrors
    link_errors: LinkErrors
    timestamp: float

    @property
    def name(self) -> str:
        """Return the stable display key in device:port form."""
        return self.status.name

    @property
    def total_mb_s(self) -> float:
        """Return combined RX and TX throughput in MB/s."""
        return self.io.rx_mb_s + self.io.tx_mb_s

    @property
    def total_packets_s(self) -> float:
        """Return combined RX and TX packet rate."""
        return self.io.rx_packets_s + self.io.tx_packets_s

    @property
    def total_errors(self) -> int:
        """Return combined interface and link error counters."""
        return self.errors.total + self.link_errors.total


class RateCalculator:
    """Convert raw monotonic sysfs snapshots into per-second metrics."""

    def __init__(self) -> None:
        """Create an empty previous-sample cache."""
        self._previous: dict[str, InterfaceSnapshot] = {}

    def update(self, snapshots: Iterable[InterfaceSnapshot]) -> list[InterfaceMetrics]:
        """Return display metrics and retain samples for the next delta calculation."""
        ordered = sorted(snapshots, key=lambda sample: sample.status.name)
        metrics: list[InterfaceMetrics] = []

        for snapshot in ordered:
            previous = self._previous.get(snapshot.status.name)
            metrics.append(self._from_snapshot(snapshot, previous))

        self._previous = {snapshot.status.name: snapshot for snapshot in ordered}
        return metrics

    def _from_snapshot(
        self,
        snapshot: InterfaceSnapshot,
        previous: InterfaceSnapshot | None,
    ) -> InterfaceMetrics:
        """Build one metric record from the current and previous raw samples."""
        interval = 0.0
        if previous is not None:
            interval = max(snapshot.timestamp - previous.timestamp, 0.0)

        io = IORates(
            rx_packets_s=self._rate(snapshot, previous, "port_rcv_packets", interval),
            rx_mb_s=self._data_mb_rate(snapshot, previous, "port_rcv_data", interval),
            tx_packets_s=self._rate(snapshot, previous, "port_xmit_packets", interval),
            tx_mb_s=self._data_mb_rate(snapshot, previous, "port_xmit_data", interval),
            uc_rx_packets_s=self._rate(snapshot, previous, "unicast_rcv_packets", interval),
            uc_tx_packets_s=self._rate(snapshot, previous, "unicast_xmit_packets", interval),
            mc_rx_packets_s=self._rate(snapshot, previous, "multicast_rcv_packets", interval),
            mc_tx_packets_s=self._rate(snapshot, previous, "multicast_xmit_packets", interval),
        )

        errors = InterfaceErrors(
            symbol=self._counter(snapshot, "symbol_error"),
            rx=self._counter(snapshot, "port_rcv_errors"),
            rx_remote_physical=self._counter(snapshot, "port_rcv_remote_physical_errors"),
            rx_switch_relay=self._counter(snapshot, "port_rcv_switch_relay_errors"),
            rx_constraint=self._counter(snapshot, "port_rcv_constraint_errors"),
            tx_constraint=self._counter(snapshot, "port_xmit_constraint_errors"),
            buffer_overrun=self._counter(snapshot, "excessive_buffer_overrun_errors"),
            tx_discard=self._counter(snapshot, "port_xmit_discards"),
            vl15_dropped=self._counter(snapshot, "VL15_dropped"),
        )

        link_errors = LinkErrors(
            link_error_recovery=self._counter(snapshot, "link_error_recovery"),
            local_link_integrity=self._counter(snapshot, "local_link_integrity_errors"),
            link_downed=self._counter(snapshot, "link_downed"),
        )

        return InterfaceMetrics(
            status=snapshot.status,
            io=io,
            errors=errors,
            link_errors=link_errors,
            timestamp=snapshot.timestamp,
        )

    @staticmethod
    def _counter(snapshot: InterfaceSnapshot, name: str) -> int:
        """Read a counter value, defaulting missing counters to zero."""
        return int(snapshot.counters.get(name, 0))

    def _rate(
        self,
        snapshot: InterfaceSnapshot,
        previous: InterfaceSnapshot | None,
        name: str,
        interval: float,
    ) -> float:
        """Convert a monotonic counter delta into a per-second rate."""
        if previous is None or interval <= 0.0:
            return 0.0

        current = self._counter(snapshot, name)
        old = self._counter(previous, name)
        if current < old:
            return 0.0
        return (current - old) / interval

    def _data_mb_rate(
        self,
        snapshot: InterfaceSnapshot,
        previous: InterfaceSnapshot | None,
        name: str,
        interval: float,
    ) -> float:
        """Convert InfiniBand data counters into decimal MB/s."""
        words_per_second = self._rate(snapshot, previous, name, interval)
        bytes_per_second = words_per_second * INFINIBAND_DATA_COUNTER_BYTES
        return bytes_per_second / BYTES_PER_MB


_SORT_KEY_FUNCTIONS: dict[str, Callable[[InterfaceMetrics], float | int | str]] = {
    "rx": lambda item: item.io.rx_mb_s,
    "tx": lambda item: item.io.tx_mb_s,
    "total": lambda item: item.total_mb_s,
    "errors": lambda item: item.total_errors,
    "name": lambda item: item.name,
}


def sort_metrics(metrics: Iterable[InterfaceMetrics], sort_key: str) -> list[InterfaceMetrics]:
    """Sort metrics by a supported top-style key."""
    items = list(metrics)
    key = sort_key if sort_key in _SORT_KEY_FUNCTIONS else "name"
    return sorted(items, key=_SORT_KEY_FUNCTIONS[key], reverse=key != "name")
