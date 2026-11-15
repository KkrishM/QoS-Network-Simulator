"""Streamlit dashboard for the QoS network traffic simulator."""

import pandas as pd
import plotly.express as px
import streamlit as st

from qos_simulator import ALGORITHMS, TRAFFIC_CLASSES, SimulationConfig, compare_algorithms


st.set_page_config(page_title="QoS Network Simulator", page_icon="📡", layout="wide")
st.title("📡 Intelligent QoS Network Traffic Simulator")
st.caption("Explore simulated QoS scheduling or run a small, authorized live lab link measurement.")

with st.sidebar:
    st.header("Mode")
    mode = st.radio("Choose a mode", ("Simulation", "Live lab measurement"))

if mode == "Live lab measurement":
    from live_measurement import (
        IPERF3_PORT,
        MAX_BANDWIDTH_MBPS,
        MAX_DURATION_SECONDS,
        run_udp_measurement,
    )

    st.subheader("Live UDP measurement with iperf3")
    st.warning(
        "This sends real UDP traffic to a lab server. It measures the link only; "
        "it does not configure router QoS or prioritize application traffic. "
        "Use only a private lab device you own or are authorized to test."
    )
    st.markdown(
        "Start an iperf3 server on the other lab computer (`iperf3 --server`), "
        "then enter its private IPv4 address below. The test is limited to 10 seconds "
        "and 5 Mbps."
    )
    with st.form("live_measurement_form"):
        server_ip = st.text_input("Lab server private IPv4 address", value="127.0.0.1")
        live_duration = st.slider("Test duration (seconds)", 1, MAX_DURATION_SECONDS, 5)
        live_rate = st.slider(
            "UDP test rate (Mbps)",
            min_value=0.1,
            max_value=MAX_BANDWIDTH_MBPS,
            value=1.0,
            step=0.1,
        )
        authorized = st.checkbox("I own this lab server or have permission to test it.")
        run_live_test = st.form_submit_button("Run live measurement")

    if run_live_test:
        if not authorized:
            st.error("Confirm that you are authorized to test this lab server.")
        else:
            try:
                live_result = run_udp_measurement(server_ip, live_duration, live_rate)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success(
                    f"Measurement completed against {live_result.server_ip}:"
                    f"{IPERF3_PORT}."
                )
                metric_columns = st.columns(4)
                metric_columns[0].metric("Measured throughput", f"{live_result.throughput_mbps:.3f} Mbps")
                metric_columns[1].metric("UDP jitter", f"{live_result.jitter_ms:.3f} ms")
                metric_columns[2].metric("Packet loss", f"{live_result.packet_loss_percent:.2f}%")
                metric_columns[3].metric("Packets lost", f"{live_result.packets_lost} / {live_result.packets_sent}")
                st.caption(
                    f"Configured UDP rate: {live_result.target_mbps:g} Mbps · "
                    f"Test duration: {live_result.duration_seconds} seconds · "
                    "These are measurements from this test flow, not all network traffic."
                )
    st.stop()

st.caption(
    "Explore how FIFO, Priority Queuing, and Weighted Fair Queuing handle competing "
    "applications when link bandwidth is limited."
)

with st.sidebar:
    st.header("Simulation setup")
    duration = st.slider("Traffic generation period (seconds)", 1, 30, 10)
    bandwidth = st.slider("Available link bandwidth (Mbps)", 0.1, 10.0, 0.2, 0.05)
    buffer_capacity = st.slider("Shared queue capacity (waiting packets)", 1, 500, 50)
    seed = st.number_input("Random seed", min_value=0, max_value=2_147_483_647, value=7, step=1)
    st.caption("Use the same seed to reproduce a traffic pattern.")

    st.subheader("Packets to generate")
    packet_counts = {
        traffic_class.name: st.slider(
            f"{traffic_class.name}",
            min_value=0,
            max_value=500,
            value=100,
            step=10,
            key=f"count_{traffic_class.name}",
        )
        for traffic_class in TRAFFIC_CLASSES
    }

    selected_algorithm = st.selectbox("Scheduler to inspect", ALGORITHMS)

if not any(packet_counts.values()):
    st.error("Generate at least one packet by increasing a traffic class count.")
    st.stop()

config = SimulationConfig(
    packet_counts=packet_counts,
    duration_seconds=float(duration),
    link_mbps=float(bandwidth),
    queue_capacity=int(buffer_capacity),
    seed=int(seed),
)
results = compare_algorithms(config)
selected_result = results[selected_algorithm]

st.info(
    "This mode is a packet-level simulation, not a live network test. Each run uses the same "
    "generated packets for a fair scheduler comparison."
)

summary = selected_result.summary
metric_columns = st.columns(5)
metric_values = (
    ("Throughput", f"{summary['Throughput (Mbps)']:.3f} Mbps"),
    ("Average latency", f"{summary['Avg latency (ms)']:.2f} ms"),
    ("P95 latency", f"{summary['P95 latency (ms)']:.2f} ms"),
    ("Packet loss", f"{summary['Packet loss (%)']:.2f}%"),
    ("Link utilization", f"{summary['Bandwidth utilization (%)']:.1f}%"),
)
for column, (label, value) in zip(metric_columns, metric_values):
    column.metric(label, value)

comparison_rows = [
    {"Scheduler": algorithm, **result.summary}
    for algorithm, result in results.items()
]
comparison = pd.DataFrame(comparison_rows).set_index("Scheduler")

st.subheader("Scheduler comparison")
st.dataframe(
    comparison[
        [
            "Throughput (Mbps)",
            "Avg latency (ms)",
            "P95 latency (ms)",
            "Packet loss (%)",
            "Bandwidth utilization (%)",
            "Delivered packets",
            "Dropped packets",
        ]
    ].style.format(
        {
            "Throughput (Mbps)": "{:.3f}",
            "Avg latency (ms)": "{:.2f}",
            "P95 latency (ms)": "{:.2f}",
            "Packet loss (%)": "{:.2f}%",
            "Bandwidth utilization (%)": "{:.1f}%",
        }
    ),
    width="stretch",
)

throughput_tab, latency_tab, traffic_tab, trace_tab = st.tabs(
    ["Throughput & utilization", "Latency & packet loss", "Traffic classes", "Packet trace"]
)
with throughput_tab:
    chart_data = pd.DataFrame(comparison_rows)
    left, right = st.columns(2)
    left.plotly_chart(
        px.bar(
            chart_data,
            x="Scheduler",
            y="Throughput (Mbps)",
            color="Scheduler",
            title="Delivered throughput",
        ),
        width="stretch",
    )
    right.plotly_chart(
        px.bar(
            chart_data,
            x="Scheduler",
            y="Bandwidth utilization (%)",
            color="Scheduler",
            title="Link utilization",
        ),
        width="stretch",
    )
with latency_tab:
    chart_data = pd.DataFrame(comparison_rows).melt(
        id_vars="Scheduler",
        value_vars=["Avg latency (ms)", "P95 latency (ms)"],
        var_name="Latency metric",
        value_name="Latency (ms)",
    )
    st.plotly_chart(
        px.bar(
            chart_data,
            x="Scheduler",
            y="Latency (ms)",
            color="Latency metric",
            barmode="group",
            title="Average and 95th-percentile packet latency",
        ),
        width="stretch",
    )
    st.plotly_chart(
        px.bar(
            pd.DataFrame(comparison_rows),
            x="Scheduler",
            y="Packet loss (%)",
            color="Scheduler",
            title="Packets dropped because the shared waiting queue was full",
        ),
        width="stretch",
    )
with traffic_tab:
    class_frame = pd.DataFrame(selected_result.per_class)
    left, right = st.columns(2)
    left.plotly_chart(
        px.bar(
            class_frame,
            x="Traffic class",
            y=["Delivered", "Dropped"],
            barmode="group",
            title=f"Delivered and dropped packets — {selected_algorithm}",
        ),
        width="stretch",
    )
    right.plotly_chart(
        px.bar(
            class_frame,
            x="Traffic class",
            y="Bandwidth share (%)",
            color="Traffic class",
            title="Share of delivered traffic",
        ),
        width="stretch",
    )
    st.dataframe(class_frame, width="stretch", hide_index=True)

    with st.expander("How the schedulers work"):
        st.markdown(
            "- **FIFO:** serves the packet that arrived first.\n"
            "- **Priority Queuing:** serves the highest-priority waiting class first; "
            "a packet already being transmitted is not interrupted.\n"
            "- **Weighted Fair Queuing:** serves packets by virtual finish tags, "
            "giving classes service in proportion to their configured weights."
        )
        st.caption("Traffic weights: " + ", ".join(
            f"{traffic_class.name} {traffic_class.weight:g}"
            for traffic_class in TRAFFIC_CLASSES
        ))

with trace_tab:
    st.caption(
        f"Packet-level results for {selected_algorithm}. "
        "Latency includes queue waiting and packet transmission time."
    )
    packet_frame = pd.DataFrame(selected_result.packets)
    st.download_button(
        "Download packet trace (CSV)",
        data=packet_frame.to_csv(index=False).encode("utf-8"),
        file_name=f"qos_{selected_algorithm.lower().replace(' ', '_')}_trace.csv",
        mime="text/csv",
    )
    st.dataframe(packet_frame, width="stretch", hide_index=True)
