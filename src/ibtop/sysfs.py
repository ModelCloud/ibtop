"""Linux sysfs reader for local InfiniBand/RDMA port data."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from .model import InterfaceSnapshot, InterfaceStatus

INFINIBAND_SYSFS_ROOT = Path("/sys/class/infiniband")

COUNTER_FILES: dict[str, tuple[str, ...]] = {
    "port_rcv_packets": ("port_rcv_packets_64", "port_rcv_packets"),
    "port_xmit_packets": ("port_xmit_packets_64", "port_xmit_packets"),
    "port_rcv_data": ("port_rcv_data_64", "port_rcv_data"),
    "port_xmit_data": ("port_xmit_data_64", "port_xmit_data"),
    "unicast_rcv_packets": ("unicast_rcv_packets",),
    "unicast_xmit_packets": ("unicast_xmit_packets",),
    "multicast_rcv_packets": ("multicast_rcv_packets",),
    "multicast_xmit_packets": ("multicast_xmit_packets",),
    "symbol_error": ("symbol_error",),
    "port_rcv_errors": ("port_rcv_errors",),
    "port_rcv_remote_physical_errors": ("port_rcv_remote_physical_errors",),
    "port_rcv_switch_relay_errors": ("port_rcv_switch_relay_errors",),
    "port_rcv_constraint_errors": ("port_rcv_constraint_errors",),
    "port_xmit_constraint_errors": ("port_xmit_constraint_errors",),
    "excessive_buffer_overrun_errors": ("excessive_buffer_overrun_errors",),
    "port_xmit_discards": ("port_xmit_discards",),
    "VL15_dropped": ("VL15_dropped",),
    "link_error_recovery": ("link_error_recovery",),
    "local_link_integrity_errors": ("local_link_integrity_errors",),
    "link_downed": ("link_downed",),
}


class SysfsError(RuntimeError):
    """Base error for sysfs read failures."""


class NoInterfacesError(SysfsError):
    """Raised when no matching InfiniBand sysfs interfaces are available."""


class SysfsReader:
    """Read local InfiniBand port status and counters from Linux sysfs."""

    def __init__(
        self,
        root: Path | str = INFINIBAND_SYSFS_ROOT,
        *,
        include_ethernet: bool = False,
        strict: bool = False,
    ) -> None:
        """Configure the sysfs root, link-layer filter, and error strictness."""
        self.root = Path(root)
        self.include_ethernet = include_ethernet
        self.strict = strict

    def read(self) -> list[InterfaceSnapshot]:
        """Read all matching ports under the configured sysfs root."""
        if not self.root.exists():
            raise NoInterfacesError(f"{self.root} does not exist")
        if not self.root.is_dir():
            raise SysfsError(f"{self.root} is not a directory")

        timestamp = time.monotonic()
        snapshots: list[InterfaceSnapshot] = []
        for device_path in self._iter_dirs(self.root):
            ports_path = device_path / "ports"
            if not ports_path.is_dir():
                continue
            for port_path in self._iter_dirs(ports_path):
                status = self._read_status(device_path.name, port_path)
                if not self._include_status(status):
                    continue
                counters = self._read_counters(port_path / "counters")
                snapshots.append(
                    InterfaceSnapshot(status=status, counters=counters, timestamp=timestamp)
                )

        if not snapshots:
            layer = "InfiniBand or Ethernet" if self.include_ethernet else "InfiniBand"
            raise NoInterfacesError(f"no {layer} ports found under {self.root}")
        return sorted(snapshots, key=lambda sample: sample.status.name)

    def _read_status(self, device: str, port_path: Path) -> InterfaceStatus:
        """Read identity and link-state files for one port directory."""
        port = port_path.name
        return InterfaceStatus(
            device=device,
            port=port,
            name=f"{device}:{port}",
            lid=self._read_text(port_path / "lid", default="-"),
            link_layer=self._read_text(port_path / "link_layer", default="-"),
            state=self._read_text(port_path / "state", default="-"),
            physical_state=self._read_text(port_path / "phys_state", default="-"),
            rate=self._read_text(port_path / "rate", default="-"),
        )

    def _include_status(self, status: InterfaceStatus) -> bool:
        """Return whether a port should be included in the current link-layer mode."""
        if self.include_ethernet:
            return True
        return status.link_layer.strip().lower() == "infiniband"

    def _read_counters(self, counters_path: Path) -> dict[str, int]:
        """Read every known counter using canonical names expected by the model."""
        return {
            canonical_name: self._read_first_int(counters_path, candidates)
            for canonical_name, candidates in COUNTER_FILES.items()
        }

    def _read_first_int(self, base_path: Path, candidates: Iterable[str]) -> int:
        """Read the first available counter file from a preferred-name list."""
        for filename in candidates:
            path = base_path / filename
            if path.exists():
                return self._read_int(path)
        return 0

    def _read_text(self, path: Path, *, default: str) -> str:
        """Read text with tolerant defaults unless strict mode is enabled."""
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return default
        except OSError as exc:
            if self.strict:
                raise SysfsError(f"failed to read {path}: {exc}") from exc
            return default

    def _read_int(self, path: Path) -> int:
        """Read an integer counter, accepting decimal or base-prefixed values."""
        raw = self._read_text(path, default="0").splitlines()[0].strip()
        if not raw:
            return 0
        try:
            return int(raw, 0)
        except ValueError as exc:
            if self.strict:
                raise SysfsError(f"failed to parse integer from {path}: {raw!r}") from exc
            return 0

    @staticmethod
    def _iter_dirs(path: Path) -> list[Path]:
        """Return child directories in stable numeric-then-lexical order."""
        try:
            return sorted((child for child in path.iterdir() if child.is_dir()), key=_numeric_name_key)
        except OSError:
            return []


def _numeric_name_key(path: Path) -> tuple[int, str]:
    """Sort numbered sysfs names numerically before nonnumeric names."""
    name = path.name
    if name.isdigit():
        return (0, f"{int(name):020d}")
    return (1, name)
