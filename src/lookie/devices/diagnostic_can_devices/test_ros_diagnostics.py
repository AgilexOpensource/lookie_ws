import os
import signal
import subprocess
import sys
import time
import unittest


class RosDiagnosticsTests(unittest.TestCase):
    def test_publishes_configured_devices_every_two_seconds(self):
        import rclpy
        from diagnostic_msgs.msg import DiagnosticArray
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node

        import diagnostic_can_devices_node as diagnostic

        root = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(root, "can_devices.yaml")
        original_topic, devices = diagnostic.load_config(config_path)
        topic = "/can_diagnostics_test_{}".format(os.getpid())
        context = Context()
        rclpy.init(context=context)
        subscriber = Node("can_diagnostics_test_{}".format(os.getpid()), context=context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(subscriber)
        received = []
        subscription = subscriber.create_subscription(
            DiagnosticArray, topic, lambda message: received.append((time.monotonic(), message)), 10
        )
        process = subprocess.Popen(
            [sys.executable, os.path.join(root, "diagnostic_can_devices_node.py"),
             "--config", config_path, "--ros-args", "-r", original_topic + ":=" + topic],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 15
            while len(received) < 3 and time.monotonic() < deadline and process.poll() is None:
                executor.spin_once(timeout_sec=0.2)
            self.assertGreaterEqual(
                len(received), 3,
                "Did not receive three DiagnosticArray messages; exit code: {}; output: {}".format(
                    process.poll(), process.stdout.read() if process.poll() is not None else "node still running"
                ),
            )
            links = diagnostic.read_links("ip")
            for unused_time, message in received:
                self.assertEqual([status.name for status in message.status], [device.name for device in devices])
                self.assertGreater(message.header.stamp.sec, 0)
                for status in message.status:
                    self.assertEqual(status.hardware_id, status.name)
                    self.assertIn("expected_bitrate", {value.key for value in status.values})
                    if status.name not in links:
                        self.assertEqual(status.level, bytes([diagnostic.ERROR]))
                        self.assertEqual(status.message, "CAN interface not found")
            for previous, current in zip(received, received[1:]):
                self.assertAlmostEqual(current[0] - previous[0], 2.0, delta=0.5)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                output, unused_stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                output, unused_stderr = process.communicate()
            executor.shutdown()
            subscriber.destroy_subscription(subscription)
            subscriber.destroy_node()
            rclpy.try_shutdown(context=context)
        self.assertEqual(process.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
