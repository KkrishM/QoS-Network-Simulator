"""Bounded iperf3 UDP measurements for explicitly authorized private lab hosts."""

from __future__ import annotations

import ipaddress
import json
import math
import shutil
import subprocess
from dataclasses import dataclass


MAX_DURATION_SECONDS = 10
MAX_BANDWIDTH_MBPS = 5.0
IPERF3_PORT = 5201
PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@dataclass(frozen=True)
class LiveMeasurement:
    server_ip: str
    duration_seconds: int
    target_mbps: float
    throughput_mbps: float
    jitter_ms: float
    packets_sent: int
    packets_lost: int
    packet_loss_percent: float


def validate_lab_target(server_ip: str, duration_seconds: int, target_mbps: float) -> str:
    """Validate an explicit private IPv4 lab endpoint and conservative test limits."""
    try:
        address = ipaddress.ip_address(server_ip.strip())
    except ValueError as exc:
        raise ValueError("Enter a literal private or loopback IP address; hostnames are not allowed.") from exc

    if not isinstance(address, ipaddress.IPv4Address) or not (
        address.is_loopback or any(address in network for network in PRIVATE_IPV4_NETWORKS)
    ):
        raise ValueError("Live tests are restricted to private or loopback IPv4 lab addresses.")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
        raise ValueError(f"Test duration must be between 1 and {MAX_DURATION_SECONDS} seconds.")
    if (
        isinstance(target_mbps, bool)
        or not isinstance(target_mbps, (int, float))
        or not math.isfinite(target_mbps)
        or not 0.1 <= target_mbps <= MAX_BANDWIDTH_MBPS
    ):
        raise ValueError(f"Target rate must be between 0.1 and {MAX_BANDWIDTH_MBPS:g} Mbps.")
    return str(address)


def _parse_iperf_result(
    payload: dict[str, object],
    server_ip: str,
    duration_seconds: int,
    target_mbps: float,
) -> LiveMeasurement:
    error = payload.get("error")
    if error:
        raise RuntimeError(f"iperf3 reported an error: {error}")
    end = payload.get("end")
    if not isinstance(end, dict):
        raise RuntimeError("iperf3 returned no measurement summary.")
    summary = end.get("sum")
    if not isinstance(summary, dict):
        summary = end.get("sum_received")
    if not isinstance(summary, dict):
        raise RuntimeError("iperf3 returned no UDP summary. Check the server version and try again.")

    try:
        bits_per_second = float(summary["bits_per_second"])
        jitter_ms = float(summary.get(" jitter_ms", summary.get("jitter_ms", 0.0)))
        packets_sent = int(summary["packets"])
        packets_lost = int(summary["lost_packets"])
        packet_loss_percent = float(summary["lost_percent"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("iperf3's UDP summary is missing expected packet or throughput metrics.") from exc

    values = (bits_per_second, jitter_ms, packet_loss_percent)
    if any(not math.isfinite(value) or value < 0 for value in values) or packets_sent < 0 or packets_lost < 0:
        raise RuntimeError("iperf3 returned invalid negative or non-finite metrics.")
    return LiveMeasurement(
        server_ip=server_ip,
        duration_seconds=duration_seconds,
        target_mbps=target_mbps,
        throughput_mbps=bits_per_second / 1_000_000,
        jitter_ms=jitter_ms,
        packets_sent=packets_sent,
        packets_lost=packets_lost,
        packet_loss_percent=packet_loss_percent,
    )


def run_udp_measurement(
    server_ip: str,
    duration_seconds: int,
    target_mbps: float,
) -> LiveMeasurement:
    """Send a rate-limited UDP test to one explicitly supplied private lab host."""
    validated_ip = validate_lab_target(server_ip, duration_seconds, target_mbps)
    executable = shutil.which("iperf3")
    if executable is None:
        raise RuntimeError(
            "iperf3 was not found. Install iperf3 on this computer and on your lab server, "
            "then make sure the iperf3 command is available in PATH."
        )

    command = [
        executable,
        "--client",
        validated_ip,
        "--port",
        str(IPERF3_PORT),
        "--udp",
        "--bitrate",
        f"{target_mbps:g}M",
        "--time",
        str(duration_seconds),
        "--json",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=duration_seconds + 15,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("iperf3 timed out. Confirm the lab server is running and reachable.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start iperf3: {exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip() or "iperf3 did not return valid JSON."
        raise RuntimeError(f"Could not read the iperf3 result: {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("iperf3 returned an unexpected result format.")
    if completed.returncode != 0:
        detail = payload.get("error") or completed.stderr.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"iperf3 failed: {detail}")
    return _parse_iperf_result(payload, validated_ip, duration_seconds, float(target_mbps))
