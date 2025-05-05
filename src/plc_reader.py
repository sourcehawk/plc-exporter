"""
This module provides a class to read values from a modbus TCP PLC given the configuration.
"""

from typing import Callable
from enum import Enum
from math import ceil
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.payload import BinaryPayloadDecoder as BPD
from pymodbus.pdu import ModbusResponse
from pymodbus.constants import Endian as ModbusEndian


class PLCReadException(Exception):
    """
    Raised when an error occurs while reading from a PLC.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class PLCReadConnectionError(PLCReadException):
    """
    Raised when an error occurs while connecting to a PLC.
    """


class PLCReadError(PLCReadException):
    """
    Raised when an error occurs while reading from a PLC.
    """


class PLCDecodeError(PLCReadException):
    """
    Raised when an error occurs while decoding data from a PLC.
    """


class PLCEndianness(Enum):
    """
    The endianness of the data in the PLC.
    """

    BIG = "big"
    LITTLE = "little"

    def as_modbus_endian(self) -> ModbusEndian:
        """
        Convert the endianness to a pymodbus endian.
        """
        return {
            PLCEndianness.BIG: ModbusEndian.BIG,
            PLCEndianness.LITTLE: ModbusEndian.LITTLE,
        }[self]


class PLCRegisterType(Enum):
    """
    The types of registers that can be read from a PLC.
    """

    COILS = "coils"
    DISCRETE_INPUTS = "discrete_inputs"
    INPUT_REGISTERS = "input_registers"
    HOLDING_REGISTERS = "holding_registers"


class PLCValueType(Enum):
    """
    The data types that can be read from a PLC.
    """

    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    UINT64 = "uint64"
    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    FLOAT16 = "float16"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    CHAR = "char"
    STRING = "string"
    BOOL = "bool"

    def max_value(self):
        """
        The maximum value that can be represented by the data type.
        """
        return {
            PLCValueType.UINT8: 2**8 - 1,
            PLCValueType.UINT16: 2**16 - 1,
            PLCValueType.UINT32: 2**32 - 1,
            PLCValueType.UINT64: 2**64 - 1,
            PLCValueType.INT8: 2**7 - 1,
            PLCValueType.INT16: 2**15 - 1,
            PLCValueType.INT32: 2**31 - 1,
            PLCValueType.INT64: 2**63 - 1,
            PLCValueType.FLOAT16: 2**16 - 1,
            PLCValueType.FLOAT32: 2**32 - 1,
            PLCValueType.FLOAT64: 2**64 - 1,
            PLCValueType.CHAR: 2**8 - 1,
            PLCValueType.STRING: None,
            PLCValueType.BOOL: 1,
        }[self]

    def min_value(self):
        """
        The minimum value that can be represented by the data type.
        """
        return {
            PLCValueType.UINT8: 0,
            PLCValueType.UINT16: 0,
            PLCValueType.UINT32: 0,
            PLCValueType.UINT64: 0,
            PLCValueType.INT8: -(2**7),
            PLCValueType.INT16: -(2**15),
            PLCValueType.INT32: -(2**31),
            PLCValueType.INT64: -(2**63),
            PLCValueType.FLOAT16: -(2**16),
            PLCValueType.FLOAT32: -(2**32),
            PLCValueType.FLOAT64: -(2**64),
            PLCValueType.CHAR: 0,
            PLCValueType.STRING: None,
            PLCValueType.BOOL: 0,
        }[self]


class RegisterAddress:
    """
    A class to represent a register address.
    """

    def __init__(self, address: int):
        self._address = address

    @property
    def address(self) -> int:
        """
        The address of the register.
        """
        return self._address

    def __str__(self) -> str:
        return f"0x{format(self._address, '04x')}"

    def __repr__(self) -> str:
        return f"RegisterAddress(address={self._address})"


class PLCReader:
    """
    Reads values from a modbus TCP PLC given the configuration.

    Usage:

    ```py
    plc = PLCReader(host="127.0.0.1", port=502)
    await plc.connect()
    coil_value = await plc.read(
        address=0,
        register_type=PLCRegisterType.COILS,
    )
    discrete_input_value = await plc.read(
        address=0,
        register_type=PLCRegisterType.DISCRETE_INPUTS,
    )
    input_register_value = await plc.read(
        address=0,
        register_type=PLCRegisterType.INPUT_REGISTERS,
        data_type=PLCValueType.UINT16,
    )
    holding_register_value = await plc.read(
        address=0,
        register_type=PLCRegisterType.HOLDING_REGISTERS,
        data_type=PLCValueType.FLOAT32,
    )
    holding_register_string = await plc.read(
        address=0,
        register_type=PLCRegisterType.HOLDING_REGISTERS,
        data_type=PLCValueType.STRING,
        size=10,
    )
    plc.close()
    ```
    """

    REGISTER_VTYPE = {
        PLCRegisterType.COILS: PLCValueType.BOOL,
        PLCRegisterType.DISCRETE_INPUTS: PLCValueType.BOOL,
        PLCRegisterType.INPUT_REGISTERS: None,
        PLCRegisterType.HOLDING_REGISTERS: None,
    }
    VTYPE_SIZE_BYTES = {
        PLCValueType.UINT8: 1,
        PLCValueType.UINT16: 2,
        PLCValueType.UINT32: 4,
        PLCValueType.UINT64: 8,
        PLCValueType.INT8: 1,
        PLCValueType.INT16: 2,
        PLCValueType.INT32: 4,
        PLCValueType.INT64: 8,
        PLCValueType.FLOAT16: 2,
        PLCValueType.FLOAT32: 4,
        PLCValueType.FLOAT64: 8,
        PLCValueType.CHAR: 1,
        PLCValueType.STRING: None,
        PLCValueType.BOOL: 1,
    }

    REGISTER_DECODERS: dict[
        PLCRegisterType, Callable[[ModbusResponse, PLCEndianness, PLCEndianness], BPD]
    ] = {
        PLCRegisterType.COILS: lambda r, e, w: BPD.fromCoils(
            coils=r.bits, byteorder=PLCEndianness.BIG.value, _wordorder=w
        ),
        PLCRegisterType.DISCRETE_INPUTS: lambda r, e, w: BPD.fromCoils(
            coils=r.bits, byteorder=PLCEndianness.BIG.value, _wordorder=w
        ),
        PLCRegisterType.INPUT_REGISTERS: lambda r, e, w: BPD.fromRegisters(
            registers=r.registers, byteorder=e, wordorder=w
        ),
        PLCRegisterType.HOLDING_REGISTERS: lambda r, e, w: BPD.fromRegisters(
            registers=r.registers, byteorder=e, wordorder=w
        ),
    }

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 502,
        endianness: PLCEndianness = PLCEndianness.BIG,
        word_order: PLCEndianness = PLCEndianness.BIG,
    ):
        self._host = host
        self._port = port
        self._word_order = word_order
        self._endianness = endianness
        self.__client = AsyncModbusTcpClient(host=host, port=port)
        self.__readers = {
            PLCRegisterType.COILS: self.__client.read_coils,
            PLCRegisterType.DISCRETE_INPUTS: self.__client.read_discrete_inputs,
            PLCRegisterType.INPUT_REGISTERS: self.__client.read_input_registers,
            PLCRegisterType.HOLDING_REGISTERS: self.__client.read_holding_registers,
        }

    async def read(
        self,
        address: int,
        register_type: PLCRegisterType,
        data_type: PLCValueType = PLCValueType.UINT16,
        size: int = 1,
    ):
        """
        Read a value from the PLC.

        :param address: The address of the register to read.
        :param register_type: The type of register to read.
        :param data_type: The data type of the register. (Ignored for coils and discrete inputs)
        :param size: The size of a string in bytes. Ignored for all data types except string.
        :returns: The value of the register as the type given by `data_type`.
        :raises PLCReadError: If the register could not be read.
        :raises PLCDecodeError: If the register could not be decoded.
        """
        return await self.__read(
            address=address,
            read_fn=self.__readers[register_type],
            register_type=register_type,
            data_type=PLCReader.REGISTER_VTYPE[register_type] or data_type,
            size=PLCReader.VTYPE_SIZE_BYTES[data_type] or size,
        )

    async def __read(
        self,
        address: int,
        read_fn: callable,
        register_type: PLCRegisterType,
        data_type: PLCValueType,
        size: int,
    ) -> int | str | bool:
        try:
            response = await read_fn(
                address=address,
                count=ceil(size / 2),
            )
        except ModbusException as exc:
            raise PLCReadError("Connection failed during read.") from exc

        if response.isError():
            raise PLCReadError(
                f"Unable to process register {RegisterAddress(address)} using {read_fn.__name__}"
            )

        decoder = PLCReader.REGISTER_DECODERS[register_type](
            r=response,
            e=self._endianness.as_modbus_endian(),
            w=self._word_order.as_modbus_endian(),
        )
        decode_func = {
            PLCValueType.UINT8: decoder.decode_8bit_uint,
            PLCValueType.UINT16: decoder.decode_16bit_uint,
            PLCValueType.UINT32: decoder.decode_32bit_uint,
            PLCValueType.UINT64: decoder.decode_64bit_uint,
            PLCValueType.INT8: decoder.decode_8bit_int,
            PLCValueType.INT16: decoder.decode_16bit_int,
            PLCValueType.INT32: decoder.decode_32bit_int,
            PLCValueType.INT64: decoder.decode_64bit_int,
            PLCValueType.FLOAT16: decoder.decode_16bit_float,
            PLCValueType.FLOAT32: decoder.decode_32bit_float,
            PLCValueType.FLOAT64: decoder.decode_64bit_float,
            PLCValueType.CHAR: lambda: decoder.decode_string(size=1),
            PLCValueType.STRING: lambda: decoder.decode_string(size=size),
            PLCValueType.BOOL: lambda: response.bits[0]
            if self._endianness == PLCEndianness.BIG
            else response.bits[-1],
        }[data_type]
        try:
            decode_value = decode_func()
            return decode_value
        except Exception as exc:
            raise PLCDecodeError(f"Could not decode data as {data_type}") from exc

    async def connect(self):
        """
        Connect to the PLC.

        :raises PLCReadConnectionError: If the connection could not be established.
        """
        try:
            assert await self.__client.connect()
        except AssertionError as exc:
            raise PLCReadConnectionError(
                f"Could not connect to PLC (host: {self._host}, port: {self._port})"
            ) from exc

    def close(self):
        """
        Close the connection to the PLC.
        """
        self.__client.close()
