import importlib.util
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "launch_control/scripts/launch_control.py"


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeProcess:
    def __init__(self, running):
        self.running = running
        self.calls = []

    def is_run(self):
        return self.running

    def is_not_run(self):
        return not self.running

    def get_check_status(self):
        return True

    def launch(self):
        self.calls.append("launch")
        self.running = True
        return True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def shutdown(self):
        self.calls.append("shutdown")
        self.running = False
        return True


class AutoRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("auto_retry_under_test", SOURCE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load launch_control module")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_parse_defaults_zero_and_unlimited(self):
        default = self.module.parse_auto_launch_line(["demo_once", "start"])
        self.assertIsNone(default["retry"])
        self.assertIsNone(default["message"])

        ignored_interval = self.module.parse_auto_launch_line(
            ["demo_once", "start", "true", "0", "99"]
        )
        self.assertIsNone(ignored_interval["retry"])
        self.assertIsNone(ignored_interval["message"])

        unlimited = self.module.parse_auto_launch_line(
            ["demo_listener", "start", "false", "-1", "10"]
        )
        self.assertEqual(unlimited["retry"], (False, -1, 10.0))
        self.assertIsNone(unlimited["message"])

        finite = self.module.parse_auto_launch_line(
            ["demo_talker", "restart", "True", "3", "5"]
        )
        self.assertEqual(finite["retry"], (True, 3, 5.0))

    def test_parse_invalid_count_and_interval_keep_first_operation(self):
        invalid_count = self.module.parse_auto_launch_line(
            ["demo_talker", "start", "true", "-2", "5"]
        )
        self.assertIsNone(invalid_count["retry"])
        self.assertIn("invalid auto retry count", invalid_count["message"])

        missing_interval = self.module.parse_auto_launch_line(
            ["demo_talker", "start", "true", "3"]
        )
        self.assertIsNone(missing_interval["retry"])
        self.assertIn("interval is required", missing_interval["message"])

        for interval in ("0", "-1", "nan", "inf", "soon"):
            parsed = self.module.parse_auto_launch_line(
                ["demo_talker", "start", "true", "3", interval]
            )
            self.assertIsNone(parsed["retry"])
            self.assertIn("invalid auto retry interval", parsed["message"])

    def test_stop_and_close_all_ignore_retry_fields(self):
        stop = self.module.parse_auto_launch_line(
            ["demo_talker", "stop", "true", "-1", "5"]
        )
        self.assertIsNone(stop["retry"])
        self.assertIn("ignore auto retry fields", stop["message"])

        close_all = self.module.parse_auto_launch_line(
            ["close_all", "start", "false", "3", "5"]
        )
        self.assertIsNone(close_all["retry"])
        self.assertIn("ignore auto retry fields", close_all["message"])

    def test_load_config_stores_only_valid_retry_policies(self):
        with tempfile.TemporaryDirectory(prefix="auto-retry-", dir="/tmp") as home:
            config_path = Path(home) / self.module.AUTO_LAUNCH_CONFIG_NAME
            config_path.write_text(
                "\n".join([
                    '"demo_once", "start"',
                    '"demo_talker", "start", true, 3, 5',
                    '"demo_listener", "start", false, -1, 10',
                    '"demo_zero", "start", true, 0, 5',
                    '"bad_count", "start", true, -2, 5',
                    '"bad_interval", "start", true, 3, 0',
                    '"demo_talker", "stop", true, 9, 1',
                    '"close_all", "start", true, -1, 1',
                ]) + "\n",
                encoding="utf-8",
            )
            sent = []
            logs = []
            holder = SimpleNamespace(
                home=home,
                id_type={"CLOSE_ALL": "close_all"},
                auto_retry_policies={},
                send_launch_command=lambda id_type="", op_type="": sent.append((id_type, op_type)),
            )
            with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
                self.module.LaunchControlRosNode.load_auto_launch_config(holder)

            self.assertEqual(sent, [
                ("demo_once", "start"),
                ("demo_talker", "start"),
                ("demo_listener", "start"),
                ("demo_zero", "start"),
                ("bad_count", "start"),
                ("bad_interval", "start"),
                ("demo_talker", "stop"),
                ("close_all", "start"),
            ])
            self.assertNotIn("demo_once", holder.auto_retry_policies)
            self.assertNotIn("demo_zero", holder.auto_retry_policies)
            self.assertNotIn("bad_count", holder.auto_retry_policies)
            self.assertNotIn("bad_interval", holder.auto_retry_policies)
            self.assertNotIn("demo_talker", holder.auto_retry_policies)
            listener = holder.auto_retry_policies["demo_listener"]
            self.assertFalse(listener.check_running)
            self.assertEqual(listener.retry_limit, -1)
            self.assertEqual(listener.interval, 10.0)
            self.assertIsNotNone(listener.next_at)
            self.assertTrue(any("invalid auto retry count" in message for message in logs))
            self.assertTrue(any("invalid auto retry interval" in message for message in logs))
            self.assertTrue(any("ignore auto retry fields" in message for message in logs))

    def test_watched_retry_waits_until_stopped_and_keeps_used_count(self):
        policy = self.module.AutoRetryPolicy("demo_talker", True, 3, 5, 0)
        process = FakeProcess(running=True)
        logs = []
        with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
            self.module.advance_auto_retry(policy, process, 0)
            self.module.advance_auto_retry(policy, process, 20)
            self.assertEqual(process.calls, [])
            self.assertEqual(policy.used, 0)

            process.running = False
            self.module.advance_auto_retry(policy, process, 20)
            self.module.advance_auto_retry(policy, process, 24.9)
            self.assertEqual(process.calls, [])

            self.module.advance_auto_retry(policy, process, 25)
            self.assertEqual(process.calls, ["launch"])
            self.assertEqual(policy.used, 1)
            self.assertEqual(logs, ["[retry] [demo_talker] 1/3"])
            self.assertTrue(process.running)

            self.module.advance_auto_retry(policy, process, 40)
            self.assertEqual(policy.used, 1)
            self.assertEqual(process.calls, ["launch"])

            process.running = False
            self.module.advance_auto_retry(policy, process, 40)
            self.assertEqual(process.calls, ["launch"])
            self.module.advance_auto_retry(policy, process, 45)
            self.assertEqual(process.calls, ["launch", "launch"])
            self.assertEqual(policy.used, 2)
            self.assertEqual(logs[-1], "[retry] [demo_talker] 2/3")

    def test_unwatched_retry_restarts_running_process_on_interval(self):
        policy = self.module.AutoRetryPolicy("demo_listener", False, -1, 10, 0)
        running = FakeProcess(running=True)
        logs = []
        with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
            self.module.advance_auto_retry(policy, running, 9)
            self.assertEqual(running.calls, [])
            self.module.advance_auto_retry(policy, running, 10)
            self.assertEqual(running.calls, ["stop", "launch"])
            self.assertEqual(policy.used, 1)
            self.assertEqual(logs, ["[retry] [demo_listener] 1/-1"])
            self.assertTrue(policy.armed)

            stopped = FakeProcess(running=False)
            self.module.advance_auto_retry(policy, stopped, 20)
            self.assertEqual(stopped.calls, ["launch"])
            self.assertEqual(logs[-1], "[retry] [demo_listener] 2/-1")

    def test_retry_stops_after_the_configured_count(self):
        policy = self.module.AutoRetryPolicy("demo_talker", False, 1, 5, 0)
        process = FakeProcess(running=True)
        logs = []
        with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
            self.module.advance_auto_retry(policy, process, 5)
            self.assertEqual(process.calls, ["stop", "launch"])
            self.assertFalse(policy.armed)
            self.assertEqual(logs, [
                "[retry] [demo_talker] 1/1",
                "[retry] [demo_talker] reached 1/1",
            ])
            self.module.advance_auto_retry(policy, process, 100)
            self.assertEqual(process.calls, ["stop", "launch"])

    def test_stop_and_close_all_cancel_remaining_retries(self):
        policy = self.module.AutoRetryPolicy("demo_talker", True, 3, 5, 0)
        process = FakeProcess(running=False)
        holder = self._launch_holder({"demo_talker": process}, {"demo_talker": policy})
        logs = []
        with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
            self.module.LaunchControlRosNode.cancel_auto_retry(holder, "demo_talker")
            self.module.advance_auto_retry(policy, process, 0)
            self.module.advance_auto_retry(policy, process, 5)
            self.assertEqual(process.calls, [])
            self.assertFalse(policy.armed)
            self.assertIn("[retry] [demo_talker] cancelled", logs)

            response = SimpleNamespace(success=False, message="")
            self.module.LaunchControlRosNode._handle_launch(
                holder,
                SimpleNamespace(launch_id="demo_talker", launch_op="start"),
                response,
            )
            self.assertFalse(policy.armed)
            self.assertTrue(response.success)

            with patch.object(self.module.time, "sleep"):
                policy.armed = True
                self.module.LaunchControlRosNode._handle_launch(
                    holder,
                    SimpleNamespace(launch_id="demo_talker", launch_op="stop"),
                    SimpleNamespace(success=False, message=""),
                )
            self.assertFalse(policy.armed)
            self.assertIn("shutdown", process.calls)
            self.assertEqual(logs.count("[retry] [demo_talker] cancelled"), 2)

            other = self.module.AutoRetryPolicy("demo_listener", False, -1, 10, 0)
            listener = FakeProcess(running=True)
            holder.extend_launch_dict["demo_listener"] = listener
            holder.auto_retry_policies["demo_listener"] = other
            policy.armed = True
            self.module.LaunchControlRosNode._handle_launch(
                holder,
                SimpleNamespace(launch_id="close_all", launch_op="start"),
                SimpleNamespace(success=False, message=""),
            )
            self.assertFalse(policy.armed)
            self.assertFalse(other.armed)
            self.assertIn("stop", process.calls)
            self.assertIn("stop", listener.calls)

    def _launch_holder(self, processes, policies):
        stamp = self.module.DiagnosticArray().header.stamp
        robot_config = self.module.ConfigInfo()
        robot_config.config_exist = False
        holder = SimpleNamespace(
            home=tempfile.mkdtemp(prefix="auto-retry-home-"),
            robot_config_info=robot_config,
            extend_launch_dict=processes,
            id_type={"CLOSE_ALL": "close_all"},
            auto_retry_policies=policies,
            launch_lock=threading.RLock(),
            launch_status_pub=FakePublisher(),
            launch_diagnostic_pub=FakePublisher(),
            get_clock=lambda: SimpleNamespace(
                now=lambda: SimpleNamespace(to_msg=lambda: stamp)
            ),
        )
        holder.load_robot_config = lambda: self.module.LaunchControlRosNode.load_robot_config(holder)
        holder.cancel_auto_retry = lambda launch_id: self.module.LaunchControlRosNode.cancel_auto_retry(
            holder, launch_id
        )
        holder.publish_status = lambda: self.module.LaunchControlRosNode.publish_status(holder)
        return holder


if __name__ == "__main__":
    unittest.main()
