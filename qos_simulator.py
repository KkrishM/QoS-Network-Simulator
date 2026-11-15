"""Discrete-event simulator for comparing packet scheduling policies."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Literal


Algorithm = Literal["FIFO", "Priority Queuing", "Weighted Fair Queuing"]


@dataclass(frozen=True)
class TrafficClass:
    name: str
    priority: int
    weight: float
    min_packet_bytes: int
    max_packet_bytes: int


TRAFFIC_CLASSES = (
    TrafficClass("Video Call", priority=4, weight=4.0, min_packet_bytes=500, max_packet_bytes=1000),
    TrafficClass("Web Browsing", priority=3, weight=3.0, min_packet_bytes=300, max_packet_bytes=1200),
    TrafficClass("Streaming", priority=2, weight=2.0, min_packet_bytes=900, max_packet_bytes=1400),
    TrafficClass("File Transfer", priority=1, weight=1.0, min_packet_bytes=700, max_packet_bytes=1500),
)
CLASS_BY_NAME = {traffic_class.name: traffic_class for traffic_class in TRAFFIC_CLASSES}
ALGORITHMS: tuple[Algorithm, ...] = ("FIFO", "Priority Queuing", "Weighted Fair Queuing")


@dataclass(frozen=True)
class SimulationConfig:
    packet_counts: dict[str, int]
    duration_seconds: float = 10.0
    link_mbps: float = 0.35
    queue_capacity: int = 50
    seed: int = 7

    def __post_init__(self) -> None:
        if not self.packet_counts:
            raise ValueError("At least one traffic class must be configured.")
        unknown_classes = set(self.packet_counts) - set(CLASS_BY_NAME)
        if unknown_classes:
            raise ValueError(f"Unknown traffic classes: {', '.join(sorted(unknown_classes))}.")
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in self.packet_counts.values()):
            raise ValueError("Packet counts must be non-negative integers.")
        if not any(count > 0 for count in self.packet_counts.values()):
            raise ValueError("At least one packet must be generated.")
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds <= 0
        ):
            raise ValueError("Simulation duration must be a positive finite number.")
        if (
            isinstance(self.link_mbps, bool)
            or not isinstance(self.link_mbps, (int, float))
            or not math.isfinite(self.link_mbps)
            or self.link_mbps <= 0
        ):
            raise ValueError("Link bandwidth must be a positive finite number.")
        if isinstance(self.queue_capacity, bool) or not isinstance(self.queue_capacity, int) or self.queue_capacity < 1:
            raise ValueError("Queue capacity must be a positive integer.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("Random seed must be an integer.")


@dataclass(frozen=True)
class Packet:
    sequence: int
    traffic_class: str
    arrival_ms: float
    size_bytes: int


@dataclass(frozen=True)
class SimulationResult:
    algorithm: Algorithm
    summary: dict[str, float | int]
    per_class: list[dict[str, str | float | int]]
    packets: list[dict[str, str | float | int]]


def generate_packets(config: SimulationConfig) -> list[Packet]:
    """Create reproducible packet arrivals and sizes for the configured traffic mix."""
    rng = random.Random(config.seed)
    packets: list[Packet] = []
    sequence = 0
    for traffic_class in TRAFFIC_CLASSES:
        count = config.packet_counts.get(traffic_class.name, 0)
        for _ in range(count):
            packets.append(
                Packet(
                    sequence=sequence,
                    traffic_class=traffic_class.name,
                    arrival_ms=rng.random() * config.duration_seconds * 1000,
                    size_bytes=rng.randint(traffic_class.min_packet_bytes, traffic_class.max_packet_bytes),
                )
            )
            sequence += 1
    return sorted(packets, key=lambda packet: (packet.arrival_ms, packet.sequence))


def simulate(
    packets: list[Packet],
    config: SimulationConfig,
    algorithm: Algorithm,
) -> SimulationResult:
    """Run one non-preemptive packet scheduler against an identical packet trace."""
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unsupported scheduling algorithm: {algorithm}.")
    if not packets:
        raise ValueError("The packet trace must contain at least one packet.")
    if any(
        packet.traffic_class not in CLASS_BY_NAME
        or not math.isfinite(packet.arrival_ms)
        or packet.arrival_ms < 0
        or packet.size_bytes < 1
        for packet in packets
    ):
        raise ValueError("Packets must have a known traffic class, non-negative arrival time, and positive size.")
    packets = sorted(packets, key=lambda packet: (packet.arrival_ms, packet.sequence))

    queues: dict[str, list[tuple[Packet, float]]] = {name: [] for name in CLASS_BY_NAME}
    last_virtual_finish = {name: 0.0 for name in CLASS_BY_NAME}
    dropped_records: list[dict[str, str | float | int]] = []
    delivered_records: list[dict[str, str | float | int]] = []
    virtual_time = 0.0
    now = 0.0
    next_arrival = 0
    current: tuple[Packet, float] | None = None
    current_start_ms = 0.0
    completion_ms: float | None = None
    busy_time_ms = 0.0

    while next_arrival < len(packets) or current is not None or any(queues.values()):
        next_arrival_ms = packets[next_arrival].arrival_ms if next_arrival < len(packets) else math.inf
        event_ms = min(next_arrival_ms, completion_ms if completion_ms is not None else math.inf)
        if math.isinf(event_ms):
            break

        elapsed_ms = event_ms - now
        if elapsed_ms < -1e-9:
            raise RuntimeError("Packet events are not in chronological order.")
        if algorithm == "Weighted Fair Queuing" and elapsed_ms > 0:
            active_classes = {
                name
                for name, queue in queues.items()
                if queue or (current is not None and current[0].traffic_class == name)
            }
            if active_classes:
                active_weight = sum(CLASS_BY_NAME[name].weight for name in active_classes)
                virtual_time += elapsed_ms / active_weight
        now = event_ms

        while next_arrival < len(packets) and packets[next_arrival].arrival_ms <= now + 1e-9:
            packet = packets[next_arrival]
            next_arrival += 1
            queue_length = sum(len(queue) for queue in queues.values())
            if queue_length >= config.queue_capacity:
                dropped_records.append(
                    {
                        "sequence": packet.sequence,
                        "traffic_class": packet.traffic_class,
                        "arrival_ms": packet.arrival_ms,
                        "size_bytes": packet.size_bytes,
                        "status": "Dropped",
                        "drop_reason": "Queue full",
                        "start_ms": math.nan,
                        "completion_ms": math.nan,
                        "latency_ms": math.nan,
                        "queue_wait_ms": math.nan,
                    }
                )
                continue

            finish_tag = 0.0
            if algorithm == "Weighted Fair Queuing":
                traffic_class = CLASS_BY_NAME[packet.traffic_class]
                finish_tag = max(last_virtual_finish[packet.traffic_class], virtual_time)
                finish_tag += packet.size_bytes / traffic_class.weight
                last_virtual_finish[packet.traffic_class] = finish_tag
            queues[packet.traffic_class].append((packet, finish_tag))

        if completion_ms is not None and completion_ms <= now + 1e-9:
            assert current is not None
            packet = current[0]
            delivered_records.append(
                {
                    "sequence": packet.sequence,
                    "traffic_class": packet.traffic_class,
                    "arrival_ms": packet.arrival_ms,
                    "size_bytes": packet.size_bytes,
                    "status": "Delivered",
                    "drop_reason": "",
                    "start_ms": current_start_ms,
                    "completion_ms": now,
                    "latency_ms": now - packet.arrival_ms,
                    "queue_wait_ms": current_start_ms - packet.arrival_ms,
                }
            )
            busy_time_ms += now - current_start_ms
            current = None
            completion_ms = None

        if current is None:
            candidates = [(queue[0][0], name) for name, queue in queues.items() if queue]
            if candidates:
                if algorithm == "FIFO":
                    _, selected_class = min(candidates, key=lambda item: (item[0].arrival_ms, item[0].sequence))
                elif algorithm == "Priority Queuing":
                    _, selected_class = min(
                        candidates,
                        key=lambda item: (-CLASS_BY_NAME[item[1]].priority, item[0].arrival_ms, item[0].sequence),
                    )
                else:
                    _, selected_class = min(
                        candidates,
                        key=lambda item: (queues[item[1]][0][1], item[0].arrival_ms, item[0].sequence),
                    )
                current = queues[selected_class].pop(0)
                current_start_ms = now
                completion_ms = now + current[0].size_bytes * 8 / (config.link_mbps * 1_000_000) * 1000

    all_records = sorted(
        delivered_records + dropped_records,
        key=lambda record: (float(record["arrival_ms"]), int(record["sequence"])),
    )
    delivered_bits = sum(int(record["size_bytes"]) * 8 for record in delivered_records)
    total_generated = len(packets)
    total_delivered = len(delivered_records)
    total_dropped = len(dropped_records)
    end_time_ms = max(
        config.duration_seconds * 1000,
        max((float(record["completion_ms"]) for record in delivered_records), default=0.0),
    )
    throughput_mbps = delivered_bits / (end_time_ms * 1000) if end_time_ms > 0 else 0.0
    latencies = [float(record["latency_ms"]) for record in delivered_records]
    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)

    per_class: list[dict[str, str | float | int]] = []
    for traffic_class in TRAFFIC_CLASSES:
        class_delivered = [record for record in delivered_records if record["traffic_class"] == traffic_class.name]
        class_dropped = [record for record in dropped_records if record["traffic_class"] == traffic_class.name]
        class_bits = sum(int(record["size_bytes"]) * 8 for record in class_delivered)
        class_latencies = [float(record["latency_ms"]) for record in class_delivered]
        per_class.append(
            {
                "Traffic class": traffic_class.name,
                "Priority": traffic_class.priority,
                "WFQ weight": traffic_class.weight,
                "Generated": len(class_delivered) + len(class_dropped),
                "Delivered": len(class_delivered),
                "Dropped": len(class_dropped),
                "Avg latency (ms)": sum(class_latencies) / len(class_latencies) if class_latencies else 0.0,
                "Throughput (Mbps)": class_bits / (end_time_ms * 1000) if end_time_ms > 0 else 0.0,
                "Bandwidth share (%)": class_bits / delivered_bits * 100 if delivered_bits else 0.0,
            }
        )

    summary: dict[str, float | int] = {
        "Generated packets": total_generated,
        "Delivered packets": total_delivered,
        "Dropped packets": total_dropped,
        "Packet loss (%)": total_dropped / total_generated * 100 if total_generated else 0.0,
        "Throughput (Mbps)": throughput_mbps,
        "Avg latency (ms)": sum(latencies) / len(latencies) if latencies else 0.0,
        "P95 latency (ms)": sorted_latencies[p95_index] if sorted_latencies else 0.0,
        "Avg queue wait (ms)": (
            sum(float(record["queue_wait_ms"]) for record in delivered_records) / total_delivered
            if total_delivered
            else 0.0
        ),
        "Bandwidth utilization (%)": busy_time_ms / end_time_ms * 100 if end_time_ms > 0 else 0.0,
        "Simulation time (s)": end_time_ms / 1000,
    }
    return SimulationResult(algorithm, summary, per_class, all_records)


def compare_algorithms(config: SimulationConfig) -> dict[Algorithm, SimulationResult]:
    """Compare every scheduler using exactly the same generated traffic."""
    packets = generate_packets(config)
    return {algorithm: simulate(packets, config, algorithm) for algorithm in ALGORITHMS}
