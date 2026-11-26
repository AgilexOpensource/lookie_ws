#!/usr/bin/env python3

from __future__ import annotations

import fcntl
import os
import re
import signal
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import TransformBroadcaster

try:
    from .resolver import CameraResolver
except ImportError:
    from resolver import CameraResolver


class ReadCameraNode(Node):

    def __init__(self):
        super().__init__(f"read_camera_node_{os.getpid()}")

        self.declare_parameter("camera_alias", "fisheye")
        self.camera_alias = self.get_parameter(
            "camera_alias"
        ).get_parameter_value().string_value

        default_frame = self._safe_name(self.camera_alias)

        self.declare_parameter("camera_fps", 30)
        self.declare_parameter("camera_height", 480)
        self.declare_parameter("camera_width", 640)
        self.declare_parameter("enable_fps_log", False)
        self.declare_parameter("fps_log_interval", 1.0)
        self.declare_parameter("reconnect_interval", 2.0)
        self.declare_parameter("camera_frame_id", default_frame)
        self.camera_frame_id = str(
            self.get_parameter("camera_frame_id").value
        ).lstrip("/")
        self.declare_parameter(
            "image_topic",
            f"/{self.camera_frame_id}/color/image_raw",
        )
        self.declare_parameter(
            "camera_info_topic",
            f"/{self.camera_frame_id}/color/camera_info",
        )

        self.camera_fps = int(
            self.get_parameter("camera_fps").value
        )
        self.camera_height = int(
            self.get_parameter("camera_height").value
        )
        self.camera_width = int(
            self.get_parameter("camera_width").value
        )
        
        self.image_topic = str(
            self.get_parameter("image_topic").value
        )
        self.camera_info_topic = str(
            self.get_parameter("camera_info_topic").value
        )

        self.bridge = CvBridge()
        self.cap = None
        self.timer = None
        self.lock_file = None
        self.video_device = None
        self.resolver = CameraResolver()
        self.usb_path = self.resolver.configured_usb_path(self.camera_alias)
        self.last_reconnect_attempt = 0.0
        self.read_failure_count = 0
        self.fps_logging_active = False
        self.fps_frame_count = 0
        self.fps_window_start = time.monotonic()

        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        self.image_pub = self.create_publisher(
            Image,
            self.image_topic,
            qos,
        )
        self.info_pub = self.create_publisher(
            CameraInfo,
            self.camera_info_topic,
            qos,
        )
        self.tf_broadcaster = TransformBroadcaster(self)

    @staticmethod
    def _safe_name(value: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
        return name or "camera"

    @staticmethod
    def _video_index(video_device: str) -> int | None:
        match = re.fullmatch(r"/dev/video(\d+)", video_device)
        return int(match.group(1)) if match else None

    def _acquire_alias_lock(self) -> bool:
        safe_alias = self._safe_name(self.camera_alias)
        path = f"/tmp/fisheye_ros2_{safe_alias}.lock"

        self.lock_file = open(path, "w", encoding="utf-8")

        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.get_logger().error(
                f"camera_alias '{self.camera_alias}' is already running; "
                f"usb_path={self.usb_path or 'unknown'}"
            )
            return False

        self.lock_file.write(str(os.getpid()))
        self.lock_file.flush()
        return True

    def start(self) -> bool:
        if not self._acquire_alias_lock():
            return False

        self.usb_path = self.resolver.configured_usb_path(self.camera_alias)
        if self.usb_path is None:
            self.get_logger().error(
                f"camera_alias '{self.camera_alias}' is not configured; usb_path=unknown"
            )
            return False

        self.timer = self.create_timer(0.001, self.publish_frame)
        self._try_reconnect(force=True)
        return True

    def _open_camera(self, video_device: str) -> bool:
        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(video_device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            self.get_logger().warning(
                f"failed to open device={video_device} usb_path={self.usb_path}"
            )
            return False

        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.camera_fps)

        fourcc_value = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        fourcc = "".join(chr((fourcc_value >> (8 * i)) & 0xFF) for i in range(4))
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.get_logger().info(
            f"alias='{self.camera_alias}' usb_path={self.usb_path} "
            f"device={video_device} opened: "
            f"{actual_width}x{actual_height} {fourcc} @ {actual_fps:.1f} FPS"
        )
        self.video_device = video_device
        self.read_failure_count = 0
        return True

    def _try_reconnect(self, force: bool = False) -> bool:
        now = time.monotonic()
        interval = max(float(self.get_parameter("reconnect_interval").value), 0.1)
        if not force and now - self.last_reconnect_attempt < interval:
            return False

        self.last_reconnect_attempt = now
        self.get_logger().info(
            f"reconnect attempt alias='{self.camera_alias}' usb_path={self.usb_path}"
        )
        camera = self.resolver.resolve_info(self.camera_alias)
        if camera is None:
            self.get_logger().warning(
                f"camera not found alias='{self.camera_alias}' "
                f"usb_path={self.usb_path}; retry in {interval:.1f}s"
            )
            return False

        self.usb_path = camera.usb_path
        return self._open_camera(camera.device)

    def publish_frame(self) -> None:
        if self.cap is None or not self.cap.isOpened():
            self._try_reconnect()
            return

        ok, frame = self.cap.read()

        if not ok:
            self.read_failure_count += 1
            if self.read_failure_count >= 3:
                self.get_logger().warning(
                    f"camera read failed; reconnecting device={self.video_device} "
                    f"usb_path={self.usb_path}"
                )
                self.cap.release()
                self.cap = None
                self.last_reconnect_attempt = 0.0
            return

        self.read_failure_count = 0

        stamp = self.get_clock().now().to_msg()
        color_frame = self.camera_frame_id + "_color"

        image = self.bridge.cv2_to_imgmsg(frame, "bgr8")
        image.header.stamp = stamp
        image.header.frame_id = color_frame
        self.image_pub.publish(image)
        self._update_fps_log()

        info = CameraInfo()
        info.header.stamp = stamp
        info.header.frame_id = color_frame
        self.info_pub.publish(info)

        tf_msg = TransformStamped()
        tf_msg.header.stamp = stamp
        tf_msg.header.frame_id = self.camera_frame_id
        tf_msg.child_frame_id = color_frame
        tf_msg.transform.rotation.w = 1.0
        self.tf_broadcaster.sendTransform(tf_msg)

    def _update_fps_log(self) -> None:
        enabled = bool(self.get_parameter("enable_fps_log").value)
        now = time.monotonic()

        if not enabled:
            self.fps_logging_active = False
            return

        if not self.fps_logging_active:
            self.fps_logging_active = True
            self.fps_frame_count = 0
            self.fps_window_start = now
            return

        self.fps_frame_count += 1
        interval = max(float(self.get_parameter("fps_log_interval").value), 0.1)
        elapsed = now - self.fps_window_start
        if elapsed >= interval:
            fps = self.fps_frame_count / elapsed
            self.get_logger().info(
                f"publish_fps={fps:.2f} usb_path={self.usb_path} "
                f"device={self.video_device}"
            )
            self.fps_frame_count = 0
            self.fps_window_start = now

    def cleanup(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

        if self.lock_file is not None:
            fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None


node_instance = None


def signal_handler(signum, frame):
    if node_instance is not None:
        node_instance.cleanup()
    if rclpy.ok():
        rclpy.shutdown()
    sys.exit(0)


def main():
    global node_instance

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    rclpy.init()
    node_instance = ReadCameraNode()

    try:
        if not node_instance.start():
            node_instance.cleanup()
            node_instance.destroy_node()
            rclpy.shutdown()
            sys.exit(1)

        rclpy.spin(node_instance)
    finally:
        if node_instance is not None:
            node_instance.cleanup()
            node_instance.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
