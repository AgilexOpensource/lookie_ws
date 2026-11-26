from __future__ import annotations

import time
from typing import Optional

import can
import rclpy
from geometry_msgs.msg import QuaternionStamped, TransformStamped, Vector3Stamped
from rclpy.node import Node
from sensor_msgs.msg import FluidPressure, Imu
from tf2_ros import TransformBroadcaster

from .protocol import (
    ACCELERATION,
    ANGULAR_VELOCITY,
    DEG_TO_RAD,
    EULER_ANGLE,
    INCLINOMETER_ANGLE,
    PRESSURE,
    QUATERNION,
    DecodedFrame,
    decode_hi04_frame,
    normalize_quaternion_xyzw,
)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class Hi04CanNode(Node):
    def __init__(self) -> None:
        super().__init__("hi04_node")

        self.declare_parameter("port_name", "")
        self.declare_parameter("channel", "can0")
        self.declare_parameter("can_interface", "socketcan")
        self.declare_parameter("node_id", 8)
        self.declare_parameter("frame_id", "hi04_link")
        self.declare_parameter("quaternion_order", "wxyz")
        self.declare_parameter("normalize_quaternion", True)
        self.declare_parameter("publish_imu", True)
        self.declare_parameter("publish_tf", False)
        self.declare_parameter("tf_parent_frame", "world")
        self.declare_parameter("acceleration_topic", "~/acceleration_mg")
        self.declare_parameter("angular_velocity_topic", "~/angular_velocity_dps")
        self.declare_parameter("euler_topic", "~/euler_deg")
        self.declare_parameter("quaternion_topic", "~/quaternion")
        self.declare_parameter("pressure_topic", "~/pressure")
        self.declare_parameter("inclinometer_topic", "~/inclinometer_deg")
        self.declare_parameter("imu_topic", "~/imu")

        parameter_names = [
            "port_name",
            "channel",
            "can_interface",
            "node_id",
            "frame_id",
            "quaternion_order",
            "normalize_quaternion",
            "publish_imu",
            "publish_tf",
            "tf_parent_frame",
            "acceleration_topic",
            "angular_velocity_topic",
            "euler_topic",
            "quaternion_topic",
            "pressure_topic",
            "inclinometer_topic",
            "imu_topic",
        ]
        self.get_logger().info("HI04 parameters:")
        for parameter in self.get_parameters(parameter_names):
            self.get_logger().info(f"  {parameter.name}: {parameter.value!r}")

        port_name = str(self.get_parameter("port_name").value)
        channel = str(self.get_parameter("channel").value)
        self.channel = port_name if port_name else channel
        self.can_interface = str(self.get_parameter("can_interface").value)
        self.node_id = int(self.get_parameter("node_id").value)
        self.frame_id = str(self.get_parameter("frame_id").value)
        self.quaternion_order = str(self.get_parameter("quaternion_order").value)
        self.normalize_quaternion = _as_bool(self.get_parameter("normalize_quaternion").value)
        self.publish_imu = _as_bool(self.get_parameter("publish_imu").value)
        self.publish_tf = _as_bool(self.get_parameter("publish_tf").value)
        self.tf_parent_frame = str(self.get_parameter("tf_parent_frame").value)
        self.acceleration_topic = str(self.get_parameter("acceleration_topic").value)
        self.angular_velocity_topic = str(self.get_parameter("angular_velocity_topic").value)
        self.euler_topic = str(self.get_parameter("euler_topic").value)
        self.quaternion_topic = str(self.get_parameter("quaternion_topic").value)
        self.pressure_topic = str(self.get_parameter("pressure_topic").value)
        self.inclinometer_topic = str(self.get_parameter("inclinometer_topic").value)
        self.imu_topic = str(self.get_parameter("imu_topic").value)

        if not 1 <= self.node_id <= 127:
            raise ValueError("node_id must be in CANopen range 1..127")
        if self.publish_tf and not self.tf_parent_frame:
            raise ValueError("tf_parent_frame must not be empty when publish_tf is true")
        if self.publish_tf and self.tf_parent_frame == self.frame_id:
            raise ValueError("tf_parent_frame and frame_id must be different")
        for name in (
            "acceleration_topic",
            "angular_velocity_topic",
            "euler_topic",
            "quaternion_topic",
            "pressure_topic",
            "inclinometer_topic",
            "imu_topic",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")

        self.accel_mg_pub = self.create_publisher(Vector3Stamped, self.acceleration_topic, 20)
        self.gyro_dps_pub = self.create_publisher(
            Vector3Stamped, self.angular_velocity_topic, 20
        )
        self.euler_deg_pub = self.create_publisher(Vector3Stamped, self.euler_topic, 20)
        self.quaternion_pub = self.create_publisher(
            QuaternionStamped, self.quaternion_topic, 20
        )
        self.pressure_pub = self.create_publisher(FluidPressure, self.pressure_topic, 20)
        self.inclinometer_deg_pub = self.create_publisher(
            Vector3Stamped, self.inclinometer_topic, 20
        )
        self.imu_pub = self.create_publisher(Imu, self.imu_topic, 20)
        self._tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None

        self._bus: Optional[can.BusABC] = None
        self._notifier: Optional[can.Notifier] = None
        self._last_warning_time = 0.0

        self._accel_mps2: Optional[tuple[float, float, float]] = None
        self._gyro_rad_s: Optional[tuple[float, float, float]] = None
        self._quat_xyzw: Optional[tuple[float, float, float, float]] = None

        self._connect_can()

    def _connect_can(self) -> None:
        self.get_logger().info(
            "Opening HI04 CAN bus: "
            f"channel={self.channel}, interface={self.can_interface}, node_id={self.node_id}"
        )
        try:
            self._bus = can.Bus(channel=self.channel, interface=self.can_interface)
            self._notifier = can.Notifier(self._bus, [self._on_can_message], timeout=1.0)
        except Exception:
            self._disconnect_can()
            raise

    def _disconnect_can(self) -> None:
        if self._notifier is not None:
            self._notifier.stop()
            self._notifier = None
        if self._bus is not None:
            self._bus.shutdown()
            self._bus = None

    def _warn_throttled(self, message: str, period: float = 2.0) -> None:
        now = time.monotonic()
        if now - self._last_warning_time >= period:
            self._last_warning_time = now
            self.get_logger().warn(message)

    def _on_can_message(self, msg: can.Message) -> None:
        if msg.is_error_frame or msg.is_remote_frame:
            return

        try:
            decoded = decode_hi04_frame(
                int(msg.arbitration_id),
                bytes(msg.data),
                self.node_id,
                self.quaternion_order,
            )
        except ValueError as exc:
            self._warn_throttled(str(exc))
            return

        if decoded is None:
            return

        stamp = self.get_clock().now().to_msg()
        if decoded.tpdo == ACCELERATION:
            self._publish_acceleration(decoded, stamp)
        elif decoded.tpdo == ANGULAR_VELOCITY:
            self._publish_angular_velocity(decoded, stamp)
        elif decoded.tpdo == EULER_ANGLE:
            self._publish_euler(decoded, stamp)
        elif decoded.tpdo == QUATERNION:
            self._publish_quaternion(decoded, stamp)
        elif decoded.tpdo == PRESSURE:
            self._publish_pressure(decoded, stamp)
        elif decoded.tpdo == INCLINOMETER_ANGLE:
            self._publish_inclinometer(decoded, stamp)

    def _new_vector_msg(self, stamp) -> Vector3Stamped:
        msg = Vector3Stamped()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        return msg

    def _publish_acceleration(self, decoded: DecodedFrame, stamp) -> None:
        msg = self._new_vector_msg(stamp)
        msg.vector.x = float(decoded.raw[0])
        msg.vector.y = float(decoded.raw[1])
        msg.vector.z = float(decoded.raw[2])
        self.accel_mg_pub.publish(msg)

        self._accel_mps2 = (decoded.values[0], decoded.values[1], decoded.values[2])
        self._publish_imu(stamp)

    def _publish_angular_velocity(self, decoded: DecodedFrame, stamp) -> None:
        msg = self._new_vector_msg(stamp)
        msg.vector.x = decoded.values[0]
        msg.vector.y = decoded.values[1]
        msg.vector.z = decoded.values[2]
        self.gyro_dps_pub.publish(msg)

        self._gyro_rad_s = tuple(value * DEG_TO_RAD for value in decoded.values)
        self._publish_imu(stamp)

    def _publish_euler(self, decoded: DecodedFrame, stamp) -> None:
        msg = self._new_vector_msg(stamp)
        msg.vector.x = decoded.values[0]
        msg.vector.y = decoded.values[1]
        msg.vector.z = decoded.values[2]
        self.euler_deg_pub.publish(msg)

    def _publish_quaternion(self, decoded: DecodedFrame, stamp) -> None:
        q = (decoded.values[0], decoded.values[1], decoded.values[2], decoded.values[3])
        if self.normalize_quaternion:
            q = normalize_quaternion_xyzw(q)

        msg = QuaternionStamped()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.quaternion.x = q[0]
        msg.quaternion.y = q[1]
        msg.quaternion.z = q[2]
        msg.quaternion.w = q[3]
        self.quaternion_pub.publish(msg)

        self._quat_xyzw = q
        self._publish_tf(q, stamp)
        self._publish_imu(stamp)

    def _publish_tf(self, q: tuple[float, float, float, float], stamp) -> None:
        if self._tf_broadcaster is None:
            return

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = self.tf_parent_frame
        transform.child_frame_id = self.frame_id
        transform.transform.rotation.x = q[0]
        transform.transform.rotation.y = q[1]
        transform.transform.rotation.z = q[2]
        transform.transform.rotation.w = q[3]
        self._tf_broadcaster.sendTransform(transform)

    def _publish_pressure(self, decoded: DecodedFrame, stamp) -> None:
        msg = FluidPressure()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.fluid_pressure = decoded.values[0]
        msg.variance = 0.0
        self.pressure_pub.publish(msg)

    def _publish_inclinometer(self, decoded: DecodedFrame, stamp) -> None:
        msg = self._new_vector_msg(stamp)
        msg.vector.x = decoded.values[0]
        msg.vector.y = decoded.values[1]
        msg.vector.z = 0.0
        self.inclinometer_deg_pub.publish(msg)

    def _publish_imu(self, stamp) -> None:
        if not self.publish_imu:
            return
        if self._accel_mps2 is None or self._gyro_rad_s is None or self._quat_xyzw is None:
            return

        msg = Imu()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.linear_acceleration.x = self._accel_mps2[0]
        msg.linear_acceleration.y = self._accel_mps2[1]
        msg.linear_acceleration.z = self._accel_mps2[2]
        msg.angular_velocity.x = self._gyro_rad_s[0]
        msg.angular_velocity.y = self._gyro_rad_s[1]
        msg.angular_velocity.z = self._gyro_rad_s[2]
        msg.orientation.x = self._quat_xyzw[0]
        msg.orientation.y = self._quat_xyzw[1]
        msg.orientation.z = self._quat_xyzw[2]
        msg.orientation.w = self._quat_xyzw[3]
        self.imu_pub.publish(msg)

    def destroy_node(self) -> bool:
        self._disconnect_can()
        return super().destroy_node()


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: Optional[Hi04CanNode] = None
    try:
        node = Hi04CanNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
