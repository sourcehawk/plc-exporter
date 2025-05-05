"""
This module contains the schema for the configuration file.
"""

from dataclasses import dataclass
from enum import Enum
import yaml
import humanfriendly
from schema import Schema, And, Or, Use, Optional
from logger import LogLevel
from plc_reader import PLCEndianness, PLCValueType, PLCRegisterType
from constants import (
    DEFAULT_SCRAPE_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_IDENTIFER,
    DEFAULT_LOG_LEVEL,
    DEFAULT_NAMESPACE,
)


class MetricLayout(Enum):
    """
    The layout of the metrics.
    """

    DYNAMIC = "dynamic"
    STATIC = "static"


PLC_EXPORTER_SCHEMA = Schema(
    {
        Optional(
            "exporter",
            default={
                "port": DEFAULT_PORT,
                "scrape_interval": DEFAULT_SCRAPE_INTERVAL,
                "log_level": DEFAULT_LOG_LEVEL,
            },
        ): {
            Optional("port", default=DEFAULT_PORT): And(
                Use(int), lambda n: 1 <= n <= 65535
            ),
            Optional("scrape_interval", default=DEFAULT_SCRAPE_INTERVAL): str,
            Optional("log_level", default=LogLevel.INFO): And(
                Use(lambda x: x.upper()), Or(*[level.name for level in LogLevel])
            ),
        },
        "plc": {
            "host": And(str, len),
            "port": And(Use(int), lambda n: 1 <= n <= 65535),
            Optional("endianness", default=PLCEndianness.BIG.value): Or(
                *[t.value for t in PLCEndianness]
            ),
            Optional("word_order", default=PLCEndianness.BIG.value): Or(
                *[t.value for t in PLCEndianness]
            ),
        },
        Optional("namespace", default=DEFAULT_NAMESPACE): And(str, len),
        Optional("identifier", default=DEFAULT_IDENTIFER): And(str, len),
        Optional("metric_layout", default=MetricLayout.DYNAMIC): Or(
            *[t.value for t in MetricLayout]
        ),
        Optional("mock", default=False): bool,
        Optional("static_labels", default={}): dict,
        Optional("coils", default=[]): [
            {
                "name": And(str, len),
                "description": str,
                "address": And(Use(int), lambda n: n >= 0),
                Optional("value_type", default=PLCValueType.BOOL.value): Or(
                    PLCValueType.BOOL.value
                ),
                Optional("register_type", default=PLCRegisterType.COILS.value): str,
                Optional("size", default=1): And(Use(int), lambda n: n > 0),
                Optional("mock", default=0): Or(0, 1, True, False),
            }
        ],
        Optional("discrete_inputs", default=[]): [
            {
                "name": And(str, len),
                "description": str,
                "address": And(Use(int), lambda n: n >= 0),
                Optional("value_type", default=PLCValueType.BOOL.value): Or(
                    PLCValueType.BOOL.value
                ),
                Optional(
                    "register_type", default=PLCRegisterType.DISCRETE_INPUTS.value
                ): str,
                Optional("size", default=1): And(Use(int), lambda n: n > 0),
                Optional("mock", default=0): Or(0, 1, True, False),
            }
        ],
        Optional("input_registers", default=[]): [
            {
                "name": And(str, len),
                "description": str,
                "address": And(Use(int), lambda n: n >= 0),
                "value_type": Or(*[t.value for t in PLCValueType]),
                Optional(
                    "register_type", default=PLCRegisterType.INPUT_REGISTERS.value
                ): str,
                Optional("size", default=1): And(Use(int), lambda n: n > 0),
                Optional("mock", default=0): Or(int, str, bool, float),
            }
        ],
        Optional("holding_registers", default=[]): [
            {
                "name": And(str, len),
                "description": str,
                "address": And(Use(int), lambda n: n >= 0),
                "value_type": Or(*[t.value for t in PLCValueType]),
                Optional(
                    "register_type", default=PLCRegisterType.HOLDING_REGISTERS.value
                ): str,
                Optional("size", default=1): And(Use(int), lambda n: n > 0),
                Optional("mock", default=0): Or(int, str, bool, float),
            }
        ],
    }
)


class ConfigError(Exception):
    """
    Raised when there is an error in the exporter configuration.
    """


@dataclass
class RegisterConfig:
    """
    Configuration for a single register.
    """

    name: str
    description: str
    address: int
    value_type: PLCValueType
    register_type: PLCRegisterType
    size: int = 1
    mock: any = 0

    @classmethod
    def from_dict(
        cls, value_type: str, register_type: str, **kwargs
    ) -> "RegisterConfig":
        """
        Create a RegisterConfig from a dictionary.
        """
        return cls(
            value_type=PLCValueType[value_type.upper()],
            register_type=PLCRegisterType[register_type.upper()],
            **kwargs,
        )

    def register_address(self) -> str:
        """
        Return the register address as a string.
        """
        return f"0x{self.address:04x}"

    def mock_value(self) -> any:
        """
        Validates and returns the mock value.
        """
        if self.value_type in [PLCValueType.CHAR, PLCValueType.STRING]:
            assert isinstance(self.mock, str), "Mock value must be a string"

            if self.value_type == PLCValueType.CHAR:
                assert len(self.mock) == 1, "Mock value must be a single character"

            return self.mock

        if self.value_type == PLCValueType.BOOL:
            assert self.mock in [0, 1, True, False], "Mock value must be a boolean"
            return bool(self.mock)

        assert (
            self.value_type.max_value() >= self.mock >= self.value_type.min_value()
        ), (
            f"Mock value out of accepted range for type {self.value_type} "
            f"[{self.value_type.min_value()}, {self.value_type.max_value()}]"
        )
        return self.mock


@dataclass
class PLCConfig:
    """
    Configuration for the PLC.
    """

    host: str
    port: int
    endianness: PLCEndianness
    word_order: PLCEndianness

    @classmethod
    def from_dict(cls, endianness: str, word_order: str, **kwargs) -> "PLCConfig":
        """
        Create a PLCConfig from a dictionary.
        """
        return cls(
            endianness=PLCEndianness[endianness.upper()],
            word_order=PLCEndianness[word_order.upper()],
            **kwargs,
        )


@dataclass
class ExporterConfig:
    """
    Configuration for the Prometheus exporter.
    """

    port: int
    scrape_interval: int
    log_level: LogLevel

    @classmethod
    def from_dict(
        cls, scrape_interval: str, log_level: str, **kwargs
    ) -> "ExporterConfig":
        """
        Create an ExporterConfig from a dictionary.
        """
        return cls(
            scrape_interval=humanfriendly.parse_timespan(scrape_interval),
            log_level=LogLevel[log_level.upper()],
            **kwargs,
        )


def load_config(config_path: str):
    """
    Loads and validates the configuration from a YAML file.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return PLC_EXPORTER_SCHEMA.validate(yaml.safe_load(f))
