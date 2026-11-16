"""Minimal protobuf wire-format codec for the panel protocol.

Hand-rolled so the integration has zero external dependencies (a missing
protobuf runtime in the HA environment caused config-flow 500s).

Wire rules (proto3): field key = (field_number << 3) | wire_type;
wire types: 0=varint, 2=length-delimited, 5=32-bit; zero-valued scalars are
omitted on encode exactly like generated proto3 serializers.
"""

from __future__ import annotations

import struct


# ---------------------------------------------------------------- encode

def encode_varint(value: int) -> bytes:
    out = bytearray()
    value &= (1 << 64) - 1
    while True:
        bits = value & 0x7F
        value >>= 7
        if value:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def encode_tag(field: int, wire_type: int) -> bytes:
    return encode_varint((field << 3) | wire_type)


def encode_varint_field(field: int, value: int) -> bytes:
    if value == 0:
        return b""
    return encode_tag(field, 0) + encode_varint(value)


def encode_bool_field(field: int, value: bool) -> bytes:
    return encode_varint_field(field, 1 if value else 0)


def encode_string_field(field: int, value: str) -> bytes:
    data = value.encode("utf-8")
    if not data:
        return b""
    return encode_tag(field, 2) + encode_varint(len(data)) + data


def encode_bytes_field(field: int, value: bytes) -> bytes:
    if not value:
        return b""
    return encode_tag(field, 2) + encode_varint(len(value)) + value


def encode_message_field(field: int, value: bytes) -> bytes:
    """Nested messages are always emitted when set, even when empty."""
    return encode_tag(field, 2) + encode_varint(len(value)) + value


def encode_float_field(field: int, value: float) -> bytes:
    if value == 0:
        return b""
    return encode_tag(field, 5) + struct.pack("<f", value)


def encode_packed_int32_field(field: int, values: list) -> bytes:
    if not values:
        return b""
    payload = b"".join(encode_varint(v) for v in values)
    return encode_tag(field, 2) + encode_varint(len(payload)) + payload


def message_to_base64(message_bytes: bytes) -> str:
    import base64
    return base64.b64encode(message_bytes).decode("ascii")


# ---------------------------------------------------------------- decode

class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            if self.pos >= len(self.data):
                raise ValueError("truncated varint")
            byte = self.data[self.pos]
            self.pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7
            if shift > 70:
                raise ValueError("varint too long")

    def read_bytes(self) -> bytes:
        length = self.read_varint()
        if self.pos + length > len(self.data):
            raise ValueError("truncated length-delimited field")
        out = self.data[self.pos:self.pos + length]
        self.pos += length
        return out

    def read_float(self) -> float:
        if self.pos + 4 > len(self.data):
            raise ValueError("truncated float")
        value = struct.unpack("<f", self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return value

    def read_tag(self) -> tuple[int, int]:
        key = self.read_varint()
        return key >> 3, key & 7


def zigzag_decode(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def zigzag_encode(value: int) -> int:
    return (value << 1) ^ (value >> 63 if value < 0 else 0)
