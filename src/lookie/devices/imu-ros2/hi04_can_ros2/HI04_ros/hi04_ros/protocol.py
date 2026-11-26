from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional


GRAVITY_MPS2 = 9.80665
DEG_TO_RAD = math.pi / 180.0


@dataclass(frozen=True)
class DecodedFrame:
    tpdo: str
    raw: tuple[int, ...]
    values: tuple[float, ...]


ACCELERATION = "ACCELERATION"
ANGULAR_VELOCITY = "ANGULAR_VELOCITY"
EULER_ANGLE = "EULER_ANGLE"
QUATERNION = "QUATERNION"
PRESSURE = "PRESSURE"
INCLINOMETER_ANGLE = "INCLINOMETER_ANGLE"

TPDO_BASE_IDS = {
    ACCELERATION: 0x180,
    ANGULAR_VELOCITY: 0x280,
    EULER_ANGLE: 0x380,
    QUATERNION: 0x480,
    PRESSURE: 0x680,
    INCLINOMETER_ANGLE: 0x780,
}

TPDO_DLC = {
    ACCELERATION: 6,
    ANGULAR_VELOCITY: 6,
    EULER_ANGLE: 6,
    QUATERNION: 8,
    PRESSURE: 4,
    INCLINOMETER_ANGLE: 8,
}


def normalize_quaternion_xyzw(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x, y, z, w = q
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1.0e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / norm, y / norm, z / norm, w / norm)


def _reorder_quaternion(
    raw: tuple[int, int, int, int],
    order: str,
) -> tuple[float, float, float, float]:
    scaled = [value / 10000.0 for value in raw]
    normalized_order = order.lower().replace(",", "").replace(" ", "")
    if sorted(normalized_order) != ["w", "x", "y", "z"]:
        normalized_order = "wxyz"

    by_name = {axis: scaled[index] for index, axis in enumerate(normalized_order)}
    return (by_name["x"], by_name["y"], by_name["z"], by_name["w"])


def decode_hi04_frame(
    arbitration_id: int,
    data: bytes,
    node_id: int,
    quaternion_order: str = "wxyz",
) -> Optional[DecodedFrame]:
    """Decode one HI04 CANopen TPDO frame.

    Returned quaternion values are ordered as x, y, z, w to match ROS messages.
    Other value tuples use the axis order from the device protocol.
    """
    frame_id = int(arbitration_id) & 0x7FF
    tpdo_by_id = {base_id + int(node_id): tpdo for tpdo, base_id in TPDO_BASE_IDS.items()}
    tpdo = tpdo_by_id.get(frame_id)
    if tpdo is None:
        return None

    expected_dlc = TPDO_DLC[tpdo]
    if len(data) < expected_dlc:
        raise ValueError(f"{tpdo} expects at least {expected_dlc} bytes, got {len(data)}")

    payload = bytes(data[:expected_dlc])
    if tpdo == ACCELERATION:
        raw = struct.unpack("<hhh", payload)
        values = tuple(value * 0.001 * GRAVITY_MPS2 for value in raw)
    elif tpdo == ANGULAR_VELOCITY:
        raw = struct.unpack("<hhh", payload)
        values = tuple(value * 0.1 for value in raw)
    elif tpdo == EULER_ANGLE:
        raw = struct.unpack("<hhh", payload)
        values = tuple(value * 0.01 for value in raw)
    elif tpdo == QUATERNION:
        raw = struct.unpack("<hhhh", payload)
        values = _reorder_quaternion(raw, quaternion_order)
    elif tpdo == PRESSURE:
        raw = (struct.unpack("<i", payload)[0],)
        values = (float(raw[0]),)
    elif tpdo == INCLINOMETER_ANGLE:
        raw = struct.unpack("<ii", payload)
        values = tuple(value * 0.01 for value in raw)
    else:
        return None

    return DecodedFrame(
        tpdo=tpdo,
        raw=tuple(int(value) for value in raw),
        values=tuple(float(value) for value in values),
    )
