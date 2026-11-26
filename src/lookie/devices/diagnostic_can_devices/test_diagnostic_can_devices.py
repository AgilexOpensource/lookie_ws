import io
import unittest
from unittest import mock

import yaml

import diagnostic_can_devices_node as diagnostic


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.config = diagnostic.DeviceConfig("can_chassis_imu", 500000, 700)
        self.link = {
            "ifname": self.config.name,
            "ifindex": 7,
            "flags": ["UP", "LOWER_UP"],
            "linkinfo": {
                "info_kind": "can",
                "info_data": {
                    "state": "ERROR-ACTIVE",
                    "bittiming": {"bitrate": 500000},
                },
            },
        }
        self.samples = [diagnostic.Sample(9, 800, 19), diagnostic.Sample(10, 800, 19)]

    def check_status(self, expected, samples=None, link=None, now=10, error=""):
        result = diagnostic.evaluate_device(
            self.config,
            self.link if link is None else link,
            self.samples if samples is None else samples,
            now,
            error,
        )
        self.assertEqual(result[0], expected, result)
        return result

    def test_old_and_new_canutils_formats(self):
        for line in (
            " can_chassis_imu@500000 800 96000 41600 19%",
            " can_chassis_imu@500k 800 96000 41600 0 19%",
        ):
            self.assertEqual(
                diagnostic.parse_canbusload_line(line, self.config.name, 10),
                diagnostic.Sample(10, 800, 19),
            )

    def test_ignore_headers_other_devices_and_invalid_lines(self):
        for line in (
            "canbusload 2026-10-19 12:00:00",
            "can_head@1000000 420 56700 26880 5%",
            "can_chassis_imu@500000 invalid 96000 41600 19%",
            "can_chassis_imu@500000 -1 96000 41600 19%",
            "can_chassis_imu@500000 800 96000 41600",
            "",
        ):
            self.assertIsNone(diagnostic.parse_canbusload_line(line, self.config.name, 10))

    def test_ok_and_threshold_boundary(self):
        self.check_status(diagnostic.OK)
        samples = [diagnostic.Sample(9, 600, 19), diagnostic.Sample(10, 800, 19)]
        result = self.check_status(diagnostic.OK, samples=samples)
        self.assertEqual(result[2]["fps"], "700.00")

    def test_low_and_zero_fps(self):
        for frames in (699, 0):
            self.check_status(
                diagnostic.WARN,
                samples=[diagnostic.Sample(9, frames, 0), diagnostic.Sample(10, frames, 0)],
            )

    def test_actual_bitrate_not_command_bitrate(self):
        self.link["linkinfo"]["info_data"]["bittiming"]["bitrate"] = 250000
        self.check_status(diagnostic.ERROR)

    def test_missing_or_down_interface(self):
        self.assertEqual(
            diagnostic.evaluate_device(self.config, None, self.samples, 10)[0],
            diagnostic.ERROR,
        )
        self.link["flags"] = []
        self.check_status(diagnostic.ERROR)

    def test_stale_and_startup_samples(self):
        self.check_status(diagnostic.STALE, samples=[])
        self.check_status(diagnostic.STALE, samples=self.samples[:1])
        self.check_status(diagnostic.STALE, now=14)

    def test_bus_errors_and_monitor_failure(self):
        self.check_status(diagnostic.ERROR, error="process exited")
        self.link["linkinfo"]["info_data"]["state"] = "BUS-OFF"
        self.check_status(diagnostic.ERROR)
        self.link["linkinfo"]["info_data"]["state"] = "ERROR-PASSIVE"
        self.check_status(diagnostic.WARN)

    def test_unknown_bitrate_and_non_can(self):
        self.link["linkinfo"]["info_data"].pop("bittiming")
        self.check_status(diagnostic.ERROR)
        self.link["linkinfo"]["info_kind"] = "vcan"
        self.check_status(diagnostic.ERROR)

    def test_configuration_validation(self):
        valid = {"devices": [{"name": "can0", "bitrate": 500000, "min_fps": 100}]}
        with mock.patch("builtins.open", mock.mock_open(read_data=yaml.safe_dump(valid))):
            topic, devices = diagnostic.load_config("unused.yaml")
        self.assertEqual(topic, "/diagnostics")
        self.assertEqual(devices, [diagnostic.DeviceConfig("can0", 500000, 100)])
        invalid = [None, [], {}, {"devices": []}, {"topic": False, **valid}]
        invalid.append({"devices": valid["devices"] * 2})
        invalid.append({"unexpected": 1, **valid})
        for field, value in (
            ("name", "any" * 10),
            ("name", "can0@500000"),
            ("bitrate", True),
            ("bitrate", 1000001),
            ("min_fps", -1),
            ("min_fps", float("nan")),
            ("min_fps", True),
        ):
            entry = dict(valid["devices"][0])
            entry[field] = value
            invalid.append({"devices": [entry]})
        for document in invalid:
            with self.subTest(document=document):
                with mock.patch("builtins.open", mock.mock_open(read_data=yaml.safe_dump(document))):
                    with self.assertRaises(ValueError):
                        diagnostic.load_config("unused.yaml")
        with mock.patch("builtins.open", mock.mock_open(read_data="devices: [")):
            with self.assertRaisesRegex(ValueError, "Invalid YAML"):
                diagnostic.load_config("unused.yaml")

    def test_ip_uses_json_and_timeout(self):
        result = mock.Mock(stdout='[{"ifname": "can0", "ifindex": 4}]')
        with mock.patch.object(diagnostic.subprocess, "run", return_value=result) as run:
            self.assertEqual(diagnostic.read_links("/usr/sbin/ip")["can0"]["ifindex"], 4)
        self.assertEqual(run.call_args.args[0], ["/usr/sbin/ip", "-details", "-json", "link", "show"])
        self.assertEqual(run.call_args.kwargs["timeout"], 1.0)

    def test_monitor_reads_samples_and_cleans_up(self):
        monitor = diagnostic.CanbusloadMonitor(self.config, "/usr/bin/canbusload")
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = io.StringIO(
            " can_chassis_imu@500000 800 96000 41600 19%\n"
            " can_chassis_imu@500000 801 96000 41600 19%\n"
        )
        process.stdin = io.StringIO()
        with mock.patch.object(diagnostic.subprocess, "Popen", return_value=process) as launch:
            monitor.ensure_started(10)
        monitor.reader.join(timeout=1)
        samples, error = monitor.snapshot()
        self.assertEqual([sample.frames for sample in samples], [800, 801])
        self.assertEqual(error, "")
        self.assertEqual(launch.call_args.args[0], ["/usr/bin/canbusload", "can_chassis_imu@500000"])
        self.assertEqual(launch.call_args.kwargs["stdin"], diagnostic.subprocess.PIPE)
        monitor.stop()
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stdin.closed)
        self.assertEqual(monitor.snapshot(), ([], ""))

    def test_monitor_process_failure_and_restart(self):
        monitor = diagnostic.CanbusloadMonitor(self.config, "/usr/bin/canbusload")
        with mock.patch.object(diagnostic.subprocess, "Popen", side_effect=OSError("cannot start")):
            monitor.ensure_started(10)
        self.assertEqual(monitor.snapshot(), ([], "cannot start"))
        process = mock.Mock()
        process.poll.return_value = 1
        process.returncode = 1
        process.stdout, process.stdin = io.StringIO(), io.StringIO()
        monitor.process = process
        monitor.error = ""
        self.assertIn("code 1", monitor.snapshot()[1])
        with mock.patch.object(diagnostic.subprocess, "Popen", side_effect=OSError("retry failed")) as launch:
            monitor.ensure_started(12)
        launch.assert_called_once()
        self.assertEqual(monitor.snapshot(), ([], "retry failed"))

    def test_monitor_stale_restarts(self):
        monitor = diagnostic.CanbusloadMonitor(self.config, "/usr/bin/canbusload")
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout, process.stdin = io.StringIO(), io.StringIO()
        monitor.process = process
        monitor.started_at = 10
        with mock.patch.object(diagnostic.subprocess, "Popen", side_effect=OSError("retry")) as launch:
            monitor.ensure_started(12)
            launch.assert_not_called()
            monitor.ensure_started(14)
            launch.assert_called_once()
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
