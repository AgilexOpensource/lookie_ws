#!/usr/bin/env python3
"""Publish YAML-configured SocketCAN diagnostics with ROS 2."""

import argparse
import collections
import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time


OK, WARN, ERROR, STALE = 0, 1, 2, 3
SAMPLE_COUNT = 2
SAMPLE_TIMEOUT = 3.5


@dataclasses.dataclass(frozen=True)
class DeviceConfig:
	name: str
	bitrate: int
	min_fps: float


@dataclasses.dataclass(frozen=True)
class Sample:
	received_at: float
	frames: int
	busload_percent: int


def parse_canbusload_line(line, expected_name, received_at):
	fields = line.split()
	if len(fields) < 5 or fields[0].split("@", 1)[0] != expected_name:
		return None
	if "@" not in fields[0]:
		return None
	try:
		percent_index = next(
			index for index in range(2, len(fields)) if fields[index].endswith("%")
		)
		counters = [int(value) for value in fields[1:percent_index]]
		percent = int(fields[percent_index][:-1])
	except (ValueError, StopIteration):
		return None
	if len(counters) not in (3, 4) or min(counters) < 0 or percent < 0:
		return None
	return Sample(received_at, counters[0], percent)


def evaluate_device(config, link, samples, now, monitor_error=""):
	values = {
		"expected_bitrate": str(config.bitrate),
		"min_fps": str(config.min_fps),
		"actual_bitrate": "unknown",
		"fps": "unknown",
		"busload_percent": "unknown",
		"sample_count": str(len(samples)),
	}
	if link is None:
		return ERROR, "CAN interface not found", values
	info = link.get("linkinfo", {})
	data = info.get("info_data", {})
	actual_bitrate = data.get("bittiming", {}).get("bitrate")
	state = data.get("state", "unknown")
	values.update(actual_bitrate=str(actual_bitrate), can_state=str(state))
	if info.get("info_kind") != "can":
		return ERROR, "Interface is not a physical CAN device", values
	if "UP" not in link.get("flags", []):
		return ERROR, "CAN interface is DOWN", values
	if state in ("BUS-OFF", "STOPPED", "SLEEPING"):
		return ERROR, "CAN state: " + state, values
	if actual_bitrate != config.bitrate:
		return ERROR, "Actual bitrate does not match configuration", values
	if monitor_error:
		values["monitor_error"] = monitor_error
		return ERROR, "canbusload monitor failed", values
	if not samples:
		return STALE, "Waiting for canbusload samples", values
	age = now - samples[-1].received_at
	values["sample_age_seconds"] = "{:.3f}".format(age)
	if age > SAMPLE_TIMEOUT:
		return STALE, "canbusload samples are stale", values
	if len(samples) < SAMPLE_COUNT:
		return STALE, "Waiting for two complete one-second samples", values
	fps = sum(sample.frames for sample in samples) / len(samples)
	busload = sum(sample.busload_percent for sample in samples) / len(samples)
	values.update(fps="{:.2f}".format(fps), busload_percent="{:.2f}".format(busload))
	if fps < config.min_fps:
		return WARN, "Frame rate below configured minimum", values
	if state in ("ERROR-WARNING", "ERROR-PASSIVE"):
		return WARN, "CAN state: " + state, values
	return OK, "Bitrate and frame rate meet requirements", values


def load_config(path):
	import yaml

	with open(path, encoding="utf-8") as stream:
		try:
			document = yaml.safe_load(stream)
		except yaml.YAMLError as exc:
			raise ValueError("Invalid YAML: " + str(exc)) from exc
	if not isinstance(document, dict):
		raise ValueError("YAML root must be a mapping")
	unknown = set(document) - {"topic", "devices"}
	if unknown:
		raise ValueError("Unknown configuration keys: " + str(unknown))
	topic = document.get("topic", "/diagnostics")
	if not isinstance(topic, str) or not topic:
		raise ValueError("topic must be a non-empty string")
	entries = document.get("devices")
	if not isinstance(entries, list) or not entries:
		raise ValueError("devices must be a non-empty list")
	devices = []
	names = set()
	for entry in entries:
		if not isinstance(entry, dict) or set(entry) != {"name", "bitrate", "min_fps"}:
			raise ValueError("Each device requires exactly name, bitrate and min_fps")
		name, bitrate, min_fps = entry["name"], entry["bitrate"], entry["min_fps"]
		if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}", name):
			raise ValueError("Invalid CAN interface name: " + str(name))
		if name in names:
			raise ValueError("Duplicate CAN interface: " + name)
		if type(bitrate) is not int or not 0 < bitrate <= 1000000:
			raise ValueError(name + ": bitrate must be an integer in [1, 1000000]")
		if type(min_fps) not in (int, float) or not math.isfinite(min_fps) or min_fps < 0:
			raise ValueError(name + ": min_fps must be a finite non-negative number")
		names.add(name)
		devices.append(DeviceConfig(name, bitrate, float(min_fps)))
	return topic, devices


def read_links(ip_command):
	result = subprocess.run(
		[ip_command, "-details", "-json", "link", "show"],
		capture_output=True,
		text=True,
		check=True,
		timeout=1.0,
	)
	return {link["ifname"]: link for link in json.loads(result.stdout)}


class CanbusloadMonitor:
	def __init__(self, config, command):
		self.config = config
		self.command = command
		self.process = None
		self.reader = None
		self.samples = collections.deque(maxlen=SAMPLE_COUNT)
		self.lock = threading.Lock()
		self.error = ""
		self.started_at = 0.0
		self.fingerprint = None

	def snapshot(self):
		with self.lock:
			samples, error = list(self.samples), self.error
		if self.process is not None and self.process.poll() is not None:
			error = error or "canbusload exited with code {}".format(self.process.returncode)
		return samples, error

	def ensure_started(self, now):
		samples, error = self.snapshot()
		last_activity = samples[-1].received_at if samples else self.started_at
		if self.process is not None and not error and now - last_activity <= SAMPLE_TIMEOUT:
			return
		self.stop()
		with self.lock:
			self.error = ""
		try:
			self.process = subprocess.Popen(
				[self.command, "{}@{}".format(self.config.name, self.config.bitrate)],
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				encoding="utf-8",
				errors="replace",
				bufsize=1,
				env=dict(os.environ, LC_ALL="C"),
			)
		except OSError as exc:
			with self.lock:
				self.error = str(exc)
			return
		self.started_at = now
		self.reader = threading.Thread(target=self._read, args=(self.process,), daemon=True)
		self.reader.start()

	def _read(self, process):
		for line in process.stdout:
			sample = parse_canbusload_line(line, self.config.name, time.monotonic())
			with self.lock:
				if self.process is not process:
					return
				if sample is not None:
					self.samples.append(sample)
				elif line.strip():
					self.error = line.strip()[:300]

	def stop(self):
		process, self.process = self.process, None
		if process is not None:
			if process.poll() is None:
				process.terminate()
				try:
					process.wait(timeout=0.3)
				except subprocess.TimeoutExpired:
					process.kill()
					process.wait()
			if self.reader is not None:
				self.reader.join(timeout=0.5)
			process.stdout.close()
			process.stdin.close()
		self.reader = None
		with self.lock:
			self.samples.clear()
			self.error = ""


def main(args=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--config",
		default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "can_devices.yaml"),
		help="YAML configuration path (default: can_devices.yaml beside this script)",
	)
	options, ros_args = parser.parse_known_args(args)
	try:
		topic, devices = load_config(options.config)
	except (OSError, ValueError, ImportError) as exc:
		parser.error("Cannot load configuration: " + str(exc))
	canbusload_command, ip_command = shutil.which("canbusload"), shutil.which("ip")
	if not canbusload_command or not ip_command:
		parser.error("Install can-utils and iproute2; canbusload and ip must be on PATH")

	try:
		import rclpy
		from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
		from rclpy.clock import Clock, ClockType
		from rclpy.executors import ExternalShutdownException
		from rclpy.node import Node
	except ImportError as exc:
		parser.error("ROS 2 dependencies unavailable; source /opt/ros/humble/setup.bash: " + str(exc))

	class DiagnosticCanDevicesNode(Node):
		def __init__(self):
			super().__init__("diagnostic_can_devices")
			self.publisher = self.create_publisher(DiagnosticArray, topic, 10)
			self.monitors = [CanbusloadMonitor(config, canbusload_command) for config in devices]
			self.timer = self.create_timer(
				2.0, self.publish_diagnostics, clock=Clock(clock_type=ClockType.STEADY_TIME)
			)
			self.get_logger().info("Monitoring {} CAN devices on {} every 2 seconds".format(len(devices), topic))

		def publish_diagnostics(self):
			system_error = ""
			try:
				links = read_links(ip_command)
			except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
				links = {}
				system_error = str(exc)
			now = time.monotonic()
			message = DiagnosticArray()
			message.header.stamp = self.get_clock().now().to_msg()
			for monitor in self.monitors:
				config = monitor.config
				link = links.get(config.name)
				eligible = evaluate_device(config, link, [], now)[0] == STALE
				fingerprint = (link.get("ifindex"), config.bitrate) if eligible else None
				if not eligible or fingerprint != monitor.fingerprint:
					monitor.stop()
					monitor.fingerprint = fingerprint
				samples, error = monitor.snapshot()
				level, description, values = evaluate_device(config, link, samples, now, error)
				if system_error:
					level, description = ERROR, "Cannot query CAN interfaces with ip"
					values["system_error"] = system_error
				status = DiagnosticStatus()
				status.name = config.name
				status.hardware_id = config.name
				status.level = bytes([level])
				status.message = description
				status.values = [KeyValue(key=key, value=value) for key, value in values.items()]
				message.status.append(status)
				if eligible:
					monitor.ensure_started(now)
			self.publisher.publish(message)

		def stop(self):
			self.timer.cancel()
			for monitor in self.monitors:
				monitor.stop()

	rclpy.init(args=[parser.prog] + ros_args)
	node = None
	try:
		node = DiagnosticCanDevicesNode()
		rclpy.spin(node)
	except (KeyboardInterrupt, ExternalShutdownException):
		pass
	finally:
		if node is not None:
			node.stop()
			node.destroy_node()
		rclpy.try_shutdown()


if __name__ == "__main__":
	main()
