import json
from unittest.mock import Mock, patch

import pytest

from live_measurement import (
    LiveMeasurement,
    _parse_iperf_result,
    run_udp_measurement,
    validate_lab_target,
)


@pytest.mark.parametrize("address", ["192.168.1.10", "10.0.0.2", "127.0.0.1"])
def test_private_and_loopback_targets_are_accepted(address: str) -> None:
    assert validate_lab_target(address, 5, 1.0) == address


@pytest.mark.parametrize(
    "address",
    ["example.com", "8.8.8.8", "::1", "224.0.0.1", "0.0.0.0", "192.0.2.1"],
)
def test_non_private_or_non_ipv4_targets_are_rejected(address: str) -> None:
    with pytest.raises(ValueError):
        validate_lab_target(address, 5, 1.0)


@pytest.mark.parametrize(
    ("duration", "rate"),
    [(0, 1.0), (11, 1.0), (5, 0), (5, 5.1)],
)
def test_live_test_limits_are_enforced(duration: int, rate: float) -> None:
    with pytest.raises(ValueError):
        validate_lab_target("192.168.1.10", duration, rate)


def test_udp_iperf_json_is_parsed() -> None:
    result = _parse_iperf_result(
        {
            "end": {
                "sum": {
                    "bits_per_second": 950_000,
                    "jitter_ms": 1.25,
                    "packets": 1000,
                    "lost_packets": 4,
                    "lost_percent": 0.4,
                }
            }
        },
        "192.168.1.10",
        5,
        1.0,
    )
    assert result == LiveMeasurement(
        server_ip="192.168.1.10",
        duration_seconds=5,
        target_mbps=1.0,
        throughput_mbps=0.95,
        jitter_ms=1.25,
        packets_sent=1000,
        packets_lost=4,
        packet_loss_percent=0.4,
    )


def test_live_runner_uses_bounded_udp_command_and_parses_output() -> None:
    payload = {
        "end": {
            "sum": {
                "bits_per_second": 900_000,
                "jitter_ms": 0.5,
                "packets": 500,
                "lost_packets": 1,
                "lost_percent": 0.2,
            }
        }
    }
    completed = Mock(returncode=0, stdout=json.dumps(payload), stderr="")
    with patch("live_measurement.shutil.which", return_value="iperf3"), patch(
        "live_measurement.subprocess.run", return_value=completed
    ) as run:
        result = run_udp_measurement("192.168.1.10", 5, 1.0)

    command = run.call_args.args[0]
    assert "--udp" in command
    assert "192.168.1.10" in command
    assert result.throughput_mbps == pytest.approx(0.9)
    assert run.call_args.kwargs["timeout"] == 20


def test_runner_reports_missing_iperf() -> None:
    with patch("live_measurement.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="iperf3 was not found"):
            run_udp_measurement("127.0.0.1", 1, 0.1)
