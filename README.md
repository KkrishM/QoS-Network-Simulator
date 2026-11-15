# Intelligent QoS Network Traffic Simulator

A Python and Streamlit Computer Networks lab project with an offline QoS
simulator and an optional bounded live UDP link measurement for an authorized
private lab host. Compare FIFO, strict Priority Queuing, and Weighted Fair
Queuing (WFQ) in simulation, or measure throughput, jitter, and packet loss
from a real iperf3 test flow.

## Features

- Reproducible packet generation for video calls, web browsing, streaming, and
  file transfers.
- Adjustable traffic volume, generation period, link bandwidth, shared queue
  capacity, and random seed.
- Side-by-side comparison using the same packet arrivals for all three
  schedulers.
- Per-class delivery, loss, latency, throughput, and bandwidth-share charts.
- Inspectable and downloadable packet-level CSV trace.
- Explicit packet transmission times, non-preemptive scheduling, shared-buffer
  drops, and WFQ virtual finish tags.
- Optional iperf3 live UDP test restricted to private/loopback IPv4 addresses,
  at most 5 Mbps, and at most 10 seconds.

## Run locally

Python 3.10 or newer is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local URL printed by Streamlit. Adjust the traffic and link settings in
the sidebar, then inspect the scheduler comparison and packet trace. Select
**Live lab measurement** in the sidebar for the separate real-network test.

## Live lab measurement

The optional live mode sends a rate-limited UDP test to one private IPv4 address
that you provide. Install `iperf3` on both computers and ensure its command is
available in PATH. On the lab computer, start the server:

```powershell
iperf3 --server
```

In the dashboard, choose **Live lab measurement**, enter the lab server's
private IPv4 address, confirm that you are authorized to test it, and run the
measurement. The client uses UDP port 5201 and reports measured throughput,
jitter, and packet loss. Keep the test on a network you own or have permission
to use. If the computers are on separate hosts, allow iperf3's TCP control and
UDP test traffic on port 5201 in the lab firewall only; do not expose the server
to the public internet.

Live mode measures only the test flow. It does not capture unrelated traffic,
apply router or operating-system QoS, or compare live FIFO/Priority/WFQ
scheduling. Actual QoS enforcement requires a separately configured and
controlled router or lab machine; the offline simulator remains the place to
compare those scheduling algorithms safely.

## Run tests

```powershell
python -m pytest -q
```

## Project files

- `app.py` — interactive Streamlit dashboard and visualizations.
- `qos_simulator.py` — packet generation, discrete-event scheduling, and metrics.
- `live_measurement.py` — private-address validation and bounded iperf3 measurements.
- `tests/test_simulator.py` — focused tests for reproducibility, scheduling,
  queue drops, and invalid settings.
- `tests/test_live_measurement.py` — validation and result parsing tests for live mode.

## Simulation model and interpretation

Packet arrivals are distributed uniformly over the configured generation
period. Each application class has a packet-size range, a strict priority, and a
WFQ weight. The link transmits one packet at a time; a packet already in
transmission is never preempted. The shared queue capacity counts packets
waiting for service (not the packet currently being transmitted). Arrivals to a
full queue are dropped.

Average and 95th-percentile latency include both queue waiting and transmission
time. Throughput is delivered payload bits divided by elapsed simulation time;
link utilization is packet transmission time divided by that same elapsed time.
Results are educational simulation estimates and are not guarantees of real
network performance.
