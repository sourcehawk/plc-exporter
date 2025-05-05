"""
PLC Prometheus Exporter
"""

import asyncio
import time
import argparse
import math

from prometheus_client import start_http_server, Gauge, Counter, Histogram
from logger import create_logger, set_level
from config import ExporterConfig, PLCConfig, RegisterConfig, MetricLayout, load_config
from constants import (
    INFO_METRIC_NAME,
    CONNECTION_METRIC_NAME,
    ERROR_FREQUENCY_METRIC_NAME,
    READ_LATENCY_METRIC_NAME,
)
from plc_reader import (
    PLCReader,
    PLCReadError,
    PLCReadConnectionError,
    PLCRegisterType,
    PLCValueType,
    RegisterAddress,
)

prometheus_metrics: dict[str, Gauge] = {}
logger = create_logger("plc_exporter")

metric_descriptions: dict[str, str] = {
    PLCRegisterType.COILS: (
        "Coils represent discrete outputs, which are binary values "
        "and are used to control physical devices like relays, motors, lights, "
        "or any output devices connected to the PLC."
        "They can be read and written to."
    ),
    PLCRegisterType.DISCRETE_INPUTS: (
        "Discrete inputs are binary values that represent the state "
        "of physical devices like sensors, switches, or any input devices connected to the PLC. "
        "They are read-only and cannot be written to."
    ),
    PLCRegisterType.INPUT_REGISTERS: (
        "Input registers are 16-bit registers that store numeric values. "
        "They are read-only and cannot be written to."
    ),
    PLCRegisterType.HOLDING_REGISTERS: (
        "Holding registers are 16-bit registers that store numeric values. "
        "They can be read and written to."
    ),
}


def __get_metric_name(
    register_config: RegisterConfig,
    metric_layout: MetricLayout,
) -> str:
    """
    Get the name of the metric based on the layout.
    """
    if metric_layout == MetricLayout.DYNAMIC:
        return register_config.register_type.value

    return register_config.name


def __get_metric_description(
    register_config: RegisterConfig, metric_layout: MetricLayout
) -> str:
    """
    Get the description of the metric based on the layout.
    """
    if metric_layout == MetricLayout.DYNAMIC:
        return metric_descriptions[register_config.register_type]

    return register_config.description


def __get_metric_labels(
    register_config: RegisterConfig,
    metric_layout: MetricLayout,
    address: int,
    value_type: str,
    static_labels: dict,
    index: int | None = None,
) -> dict:
    """
    Get the default label set for the metric.
    """
    extra = {"index": index}

    if metric_layout == MetricLayout.STATIC:
        extra = {
            "register_type": register_config.register_type.value,
            **extra,
        }

    if metric_layout == MetricLayout.DYNAMIC:
        extra = {"name": register_config.name, **extra}

    return {
        "start_address": str(RegisterAddress(address)),
        "value_type": value_type,
        **static_labels,
        **extra,
    }


def __char_metric(
    register_config: RegisterConfig,
    value: str,
    metric_layout: MetricLayout,
    namespace: str,
    static_labels: dict,
):
    """
    Create a character metric from a single register.

    The value is converted into it's numeric ASCII representation.
    """
    name = __get_metric_name(register_config, metric_layout)
    description = __get_metric_description(register_config, metric_layout)
    labels = __get_metric_labels(
        register_config=register_config,
        metric_layout=metric_layout,
        address=register_config.address,
        value_type="ascii",
        static_labels=static_labels,
    )

    if prometheus_metrics.get(name) is None:
        prometheus_metrics[name] = Gauge(
            name=name,
            documentation=description,
            namespace=namespace,
            labelnames=list(labels.keys()),
        )

    prometheus_metrics[name].labels(**labels).set(ord(value))


def __string_metric(
    register_config: RegisterConfig,
    value: str,
    metric_layout: MetricLayout,
    namespace: str,
    static_labels: dict,
):
    """
    Create a string metric from multiple registers.

    Each character is stored in a separate metric with the same `part_of` label and
    an `index` label indicating the position in the string.

    Each character is converted into its numeric ASCII representation.
    """
    description = __get_metric_description(register_config, metric_layout)
    register_count = math.ceil(len(value) / 2)
    register_addresses = [register_config.address + i for i in range(register_count)]

    for i, char in enumerate(value):
        char_value = ord(char)
        address = register_addresses[i // 2]

        name = __get_metric_name(register_config, metric_layout)
        labels = __get_metric_labels(
            register_config=register_config,
            metric_layout=metric_layout,
            address=address,
            value_type="ascii",
            static_labels=static_labels,
            index=i,
        )

        if prometheus_metrics.get(name) is None:
            prometheus_metrics[name] = Gauge(
                name=name,
                documentation=description,
                namespace=namespace,
                labelnames=list(labels.keys()),
            )
        prometheus_metrics[name].labels(**labels).set(char_value)


def __bool_metric(
    register_config: RegisterConfig,
    value: int,
    metric_layout: MetricLayout,
    namespace: str,
    static_labels: dict,
):
    """
    Create a boolean metric from a single register.
    """
    __numeric_metric(
        register_config=register_config,
        value=int(value),
        metric_layout=metric_layout,
        namespace=namespace,
        static_labels=static_labels,
    )


def __numeric_metric(
    register_config: RegisterConfig,
    value: int,
    metric_layout: MetricLayout,
    namespace: str,
    static_labels: dict,
):
    """
    Create a metric from a numeric value stored in one or two (up to 32 bits) registers.
    """
    description = __get_metric_description(register_config, metric_layout)
    name = __get_metric_name(register_config, metric_layout)
    labels = __get_metric_labels(
        register_config=register_config,
        metric_layout=metric_layout,
        address=register_config.address,
        value_type=register_config.value_type.value,
        static_labels=static_labels,
    )

    if prometheus_metrics.get(name) is None:
        prometheus_metrics[name] = Gauge(
            name=name,
            documentation=description,
            namespace=namespace,
            labelnames=list(labels.keys()),
        )

    prometheus_metrics[name].labels(**labels).set(value)


def info_metric(namespace: str, static_labels: dict):
    """
    Create a default metric which can be relied on to filter for default
    labels created by prometheus (e.g. `job`, `instance`).
    """
    if prometheus_metrics.get(INFO_METRIC_NAME) is None:
        prometheus_metrics[INFO_METRIC_NAME] = Gauge(
            name=INFO_METRIC_NAME,
            documentation="Information about the PLC Exporter",
            namespace=namespace,
            labelnames=list(static_labels.keys()),
        )

    prometheus_metrics[INFO_METRIC_NAME].labels(**static_labels)


def connection_metric(namespace: str, static_labels: dict):
    """
    Create a default metric which can be relied on to filter for default
    labels created by prometheus (e.g. `job`, `instance`).
    """
    if prometheus_metrics.get(CONNECTION_METRIC_NAME) is None:
        prometheus_metrics[CONNECTION_METRIC_NAME] = Gauge(
            name=CONNECTION_METRIC_NAME,
            documentation="Connection status to the PLC",
            namespace=namespace,
            labelnames=list(static_labels.keys()),
        )

    prometheus_metrics[CONNECTION_METRIC_NAME].labels(**static_labels)


def set_connection_metric(
    connected: bool,
    static_labels: dict,
):
    """
    Set the connection status of the PLC.
    """
    prometheus_metrics[CONNECTION_METRIC_NAME].labels(**static_labels).set(
        int(connected)
    )


def latency_metric(namespace: str, static_labels: dict):
    """
    Create a metric to track the read latency on a register.
    """
    if prometheus_metrics.get(READ_LATENCY_METRIC_NAME) is None:
        prometheus_metrics[READ_LATENCY_METRIC_NAME] = Histogram(
            name=READ_LATENCY_METRIC_NAME,
            documentation="Read latency in milliseconds on a register",
            namespace=namespace,
            labelnames=set(
                ["name", "value_type", "start_address", "index", "register_type"]
                + list(static_labels.keys())
            ),
        )


def set_latency_metric(
    register_config: RegisterConfig,
    static_labels: dict,
    latency: float,
):
    """
    Set the latency value in milliseconds on the register that was read.
    """
    labels = __get_metric_labels(
        register_config=register_config,
        metric_layout=MetricLayout.DYNAMIC,
        address=register_config.address,
        value_type=register_config.value_type.value,
        static_labels={
            "register_type": register_config.register_type.value,
            **static_labels,
        },
    )
    prometheus_metrics[READ_LATENCY_METRIC_NAME].labels(**labels).observe(latency)


def error_metric(namespace: str, static_labels: dict):
    """
    Create a default metric to track errors.
    """
    if prometheus_metrics.get(ERROR_FREQUENCY_METRIC_NAME) is None:
        prometheus_metrics[ERROR_FREQUENCY_METRIC_NAME] = Counter(
            name=ERROR_FREQUENCY_METRIC_NAME,
            documentation="Number of errors while reading from the register",
            namespace=namespace,
            labelnames=set(
                ["name", "value_type", "start_address", "register_type", "index"]
                + list(static_labels.keys())
            ),
        )


def set_error_metric(
    register_config: RegisterConfig,
    static_labels: dict,
    init: bool = False,
):
    """
    Increment the error metric.
    """
    labels = __get_metric_labels(
        register_config=register_config,
        metric_layout=MetricLayout.DYNAMIC,
        address=register_config.address,
        value_type=register_config.value_type.value,
        static_labels={
            "register_type": register_config.register_type.value,
            **static_labels,
        },
    )
    if init is not None:
        prometheus_metrics[ERROR_FREQUENCY_METRIC_NAME].labels(**labels).inc(0)
    else:
        prometheus_metrics[ERROR_FREQUENCY_METRIC_NAME].labels(**labels).inc()


def metric(
    register_config: RegisterConfig,
    value: int,
    metric_layout: MetricLayout,
    namespace: str,
    static_labels: dict,
):
    """
    Create a metric based on the data type.
    """
    type_to_metric = {
        PLCValueType.UINT8: __numeric_metric,
        PLCValueType.UINT16: __numeric_metric,
        PLCValueType.UINT32: __numeric_metric,
        PLCValueType.UINT64: __numeric_metric,
        PLCValueType.INT8: __numeric_metric,
        PLCValueType.INT16: __numeric_metric,
        PLCValueType.INT32: __numeric_metric,
        PLCValueType.INT64: __numeric_metric,
        PLCValueType.FLOAT16: __numeric_metric,
        PLCValueType.FLOAT32: __numeric_metric,
        PLCValueType.FLOAT64: __numeric_metric,
        PLCValueType.CHAR: __char_metric,
        PLCValueType.STRING: __string_metric,
        PLCValueType.BOOL: __bool_metric,
    }

    type_to_metric[register_config.value_type](
        register_config=register_config,
        value=value,
        metric_layout=metric_layout,
        namespace=namespace,
        static_labels=static_labels,
    )


async def update_metrics(
    plc: PLCReader | None,
    mock: bool,
    metric_layout: MetricLayout,
    registers: list[RegisterConfig],
    labels: dict,
    namespace: str,
):
    """
    Update the Prometheus metrics with the values read from the PLC.
    """
    if plc is not None:
        try:
            await plc.connect()
        except PLCReadConnectionError as exc:
            set_connection_metric(connected=False, static_labels=labels)
            logger.error(exc.message)
            return

    set_connection_metric(connected=True, static_labels=labels)

    for r in registers:
        try:
            if mock:
                value = r.mock_value()
                latency = 0.125
            else:
                start_time = time.perf_counter()
                value = await plc.read(r.address, r.register_type, r.value_type, r.size)
                latency = time.perf_counter() - start_time  # seconds

            set_latency_metric(
                register_config=r,
                static_labels=labels,
                latency=latency,
            )
            metric(
                register_config=r,
                value=value,
                metric_layout=metric_layout,
                namespace=namespace,
                static_labels=labels,
            )
        except PLCReadError as exc:
            logger.error(
                "Unable to read %s with name %s: %s",
                str(RegisterAddress(r.address)),
                r.name,
                exc,
            )
            logger.debug(exc, exc_info=True)
            set_error_metric(register_config=r, static_labels=labels)
            continue

    if plc is not None:
        plc.close()


async def start_exporter(port: int, scrape_interval: int, config: dict):
    """
    Start the Prometheus exporter and update the metrics at regular intervals.
    """
    plc_config = PLCConfig.from_dict(**config["plc"])
    plc = None

    start_http_server(port=port)
    logger.info("PLC Exporter started on port %i", port)

    mock = config["mock"]
    if mock:
        logger.info("Mocking enabled. Using mock values from the config")
    else:
        plc = PLCReader(
            host=plc_config.host,
            port=plc_config.port,
            endianness=plc_config.endianness,
            word_order=plc_config.word_order,
        )

    static_labels = {
        **{"plc": config["identifier"]},
        **config["static_labels"],
    }
    all_registers = (
        config["coils"]
        + config["discrete_inputs"]
        + config["input_registers"]
        + config["holding_registers"]
    )
    register_configs = [
        RegisterConfig.from_dict(**register) for register in all_registers
    ]
    namespace = config["namespace"]

    info_metric(namespace=namespace, static_labels=static_labels)
    latency_metric(namespace=namespace, static_labels=static_labels)
    error_metric(namespace=namespace, static_labels=static_labels)
    connection_metric(namespace=namespace, static_labels=static_labels)

    for register in register_configs:
        set_error_metric(
            register_config=register, static_labels=static_labels, init=True
        )

    metric_layout = MetricLayout(config["metric_layout"])

    while True:
        logger.debug("Updating metrics")
        await update_metrics(
            plc=plc,
            mock=mock,
            metric_layout=metric_layout,
            registers=register_configs,
            labels=static_labels,
            namespace=namespace,
        )
        await asyncio.sleep(scrape_interval)


def run():
    """
    Main entry point of the exporter.
    """
    parser = argparse.ArgumentParser(description="Beckhoff PLC Prometheus Exporter")
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to YAML configuration file",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    exporter_config = ExporterConfig.from_dict(**config["exporter"])

    set_level(logger, exporter_config.log_level.value)

    try:
        asyncio.run(
            start_exporter(
                port=exporter_config.port,
                scrape_interval=exporter_config.scrape_interval,
                config=config,
            )
        )
    except (KeyboardInterrupt, InterruptedError):
        logger.info("Exporter stopped")
