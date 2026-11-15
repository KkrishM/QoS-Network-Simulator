import pytest

from qos_simulator import (
    ALGORITHMS,
    Packet,
    SimulationConfig,
    compare_algorithms,
    generate_packets,
    simulate,
)


def make_config(**overrides: object) -> SimulationConfig:
    values: dict[str, object] = {
        "packet_counts": {"Video Call": 4, "Web Browsing": 4},
        "duration_seconds": 1,
        "link_mbps": 1,
        "queue_capacity": 20,
        "seed": 12,
    }
    values.update(overrides)
    return SimulationConfig(**values)  # type: ignore[arg-type]


def test_packet_generation_is_reproducible() -> None:
    config = make_config()
    assert generate_packets(config) == generate_packets(config)


def test_all_schedulers_process_the_same_traffic() -> None:
    config = make_config()
    results = compare_algorithms(config)
    assert tuple(results) == ALGORITHMS
    assert all(result.summary["Generated packets"] == 8 for result in results.values())
    assert all(result.summary["Delivered packets"] + result.summary["Dropped packets"] == 8 for result in results.values())


def test_priority_scheduler_serves_high_priority_waiting_packet_first() -> None:
    config = make_config(
        packet_counts={"File Transfer": 2, "Video Call": 1},
        link_mbps=0.008,
        duration_seconds=1,
    )
    packets = [
        # The first file packet starts immediately and is not preempted.
        # The other two packets wait together while it is being transmitted.
        Packet(0, "File Transfer", 0.0, 1000),
        Packet(1, "File Transfer", 0.1, 100),
        Packet(2, "Video Call", 0.1, 100),
    ]
    result = simulate(packets, config, "Priority Queuing")
    delivered = [packet for packet in result.packets if packet["status"] == "Delivered"]
    delivered.sort(key=lambda packet: float(packet["completion_ms"]))
    assert [packet["traffic_class"] for packet in delivered] == [
        "File Transfer",
        "Video Call",
        "File Transfer",
    ]


def test_full_shared_queue_drops_excess_waiting_packets() -> None:
    config = make_config(
        packet_counts={"Video Call": 3},
        link_mbps=0.008,
        queue_capacity=1,
    )
    packets = [
        Packet(0, "Video Call", 0.0, 1000),
        Packet(1, "Video Call", 0.1, 100),
        Packet(2, "Video Call", 0.1, 100),
    ]
    result = simulate(packets, config, "FIFO")
    assert result.summary["Delivered packets"] == 2
    assert result.summary["Dropped packets"] == 1
    assert result.summary["Packet loss (%)"] == pytest.approx(100 / 3)


@pytest.mark.parametrize(
    "overrides",
    [
        {"packet_counts": {"Video Call": -1}},
        {"packet_counts": {"Video Call": 0}},
        {"duration_seconds": 0},
        {"link_mbps": 0},
        {"queue_capacity": 0},
    ],
)
def test_invalid_simulation_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        make_config(**overrides)
