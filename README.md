# ibtop

`ibtop` is a Python-only, Linux-focused InfiniBand monitor. It reads local RDMA
device data from `/sys/class/infiniband`, displays top-style live tables, and
keeps per-interface traffic history graphs refreshed every second by default.

The initial PyPI project name is `ibtop`, version `0.1.0`.

## Features

- Port table: LID, type, state, physical state, rate, and grouped RX/TX
  columns with separate P/s, MB/s, Uni P/s, and Multi P/s
  subcolumns.
- Combined error table with grouped RX/TX counters plus interface and link
  counters.
- Per-port split graph history in the live UI: MB/s on the left and P/s
  on the right, with merged RX/TX lines in each panel and separate colors when
  the terminal supports color. Graphs use interpolated connected line glyphs
  instead of block bars, with Y-axis labels at the current 100%, 50%, and 0%
  scale marks. The graph area flexes to fill the available bottom screen space
  across the currently visible ports. A flat zero RX or TX series is omitted
  from the graph instead of drawing a noisy baseline.
- Optional Ethernet-link-layer ports with `--ethernet`.
- One-shot table output with `--once`.
- LogBar-backed logging and table formatting.

## Install

```bash
pip install ibtop
```

For local development:

```bash
python -m pip install -e .
```

## Usage

```bash
ibtop
ibtop --refresh 1 --history 120
ibtop --ethernet
ibtop --once
```

Live UI keys:

- `q`: quit
- `space`: pause or resume sampling
- `s`: cycle sort order
- `e`: toggle Ethernet-link-layer ports
- `Up` / `Down`, `PageUp` / `PageDown`: scroll

## Notes

`ibtop` currently targets Linux only. It expects standard InfiniBand sysfs
files under `/sys/class/infiniband/<device>/ports/<port>/`.

The Linux ABI documents `port_rcv_data` and `port_xmit_data` as octets divided
by 4, so `ibtop` multiplies those deltas by 4 before displaying MB/s.
