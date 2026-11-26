import math

from hi04_ros.protocol import (
    ACCELERATION,
    ANGULAR_VELOCITY,
    EULER_ANGLE,
    INCLINOMETER_ANGLE,
    PRESSURE,
    QUATERNION,
    DEG_TO_RAD,
    GRAVITY_MPS2,
    decode_hi04_frame,
)


def test_decode_acceleration_example():
    frame = decode_hi04_frame(0x188, bytes.fromhex("4A 00 1F 00 C8 03"), 8)

    assert frame is not None
    assert frame.tpdo == ACCELERATION
    assert frame.raw == (74, 31, 968)
    assert frame.values == (
        74 * 0.001 * GRAVITY_MPS2,
        31 * 0.001 * GRAVITY_MPS2,
        968 * 0.001 * GRAVITY_MPS2,
    )


def test_decode_angular_velocity_example():
    frame = decode_hi04_frame(0x288, bytes.fromhex("15 00 14 01 34 00"), 8)

    assert frame is not None
    assert frame.tpdo == ANGULAR_VELOCITY
    assert frame.raw == (21, 276, 52)
    assert frame.values == (2.1, 27.6, 5.2)
    assert math.isclose(frame.values[1] * DEG_TO_RAD, 27.6 * math.pi / 180.0)


def test_decode_euler_negative_value():
    frame = decode_hi04_frame(0x388, bytes.fromhex("1e fb 00 00 00 00"), 8)

    assert frame is not None
    assert frame.tpdo == EULER_ANGLE
    assert frame.raw[0] == -1250
    assert frame.values[0] == -12.5


def test_decode_quaternion_wxyz_to_ros_xyzw():
    frame = decode_hi04_frame(0x488, bytes.fromhex("10 27 00 00 00 00 00 00"), 8)

    assert frame is not None
    assert frame.tpdo == QUATERNION
    assert frame.raw == (10000, 0, 0, 0)
    assert frame.values == (0.0, 0.0, 0.0, 1.0)


def test_decode_pressure_and_inclinometer():
    pressure = decode_hi04_frame(0x688, (101325).to_bytes(4, "little", signed=True), 8)
    inclinometer = decode_hi04_frame(
        0x788,
        (1234).to_bytes(4, "little", signed=True) + (-567).to_bytes(4, "little", signed=True),
        8,
    )

    assert pressure is not None
    assert pressure.tpdo == PRESSURE
    assert pressure.raw == (101325,)
    assert pressure.values == (101325.0,)

    assert inclinometer is not None
    assert inclinometer.tpdo == INCLINOMETER_ANGLE
    assert inclinometer.raw == (1234, -567)
    assert inclinometer.values == (12.34, -5.67)
