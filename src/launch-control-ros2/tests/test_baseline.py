import ast
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "launch_control/scripts/launch_control.py"
BACKUP_PATH = REPO_ROOT / "launch_control/bk/launch_control.py"
BASELINE_VERSION = "ros2-20260326-1"


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bk_baseline_under_test", SOURCE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load baseline module")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.is_baseline = cls.module.VERSION == BASELINE_VERSION
        cls.has_force_kill = hasattr(cls.module.LaunchProcess, "get_force_kill")

    def test_source_parses_and_compiles(self):
        source = SOURCE_PATH.read_bytes()
        tree = ast.parse(source, filename=str(SOURCE_PATH))
        compile(tree, str(SOURCE_PATH), "exec")
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        if self.is_baseline:
            self.assertEqual(source.splitlines()[0], b"#! /usr/bin/env python3.10")
            self.assertIn("data_msgs.msg", imports)
            self.assertIn("data_msgs.srv", imports)
            self.assertFalse(any(name.startswith("launch_control_msgs") for name in imports))
            self.assertNotIn(b"force_kill", source)
            self.assertNotIn(b"diagnostic", source)
            self.assertFalse(self.has_force_kill)
        else:
            self.assertEqual(self.module.VERSION, "ros2-20260920-1")
            self.assertIn("launch_control_msgs.msg", imports)
            self.assertIn("launch_control_msgs.srv", imports)
            self.assertIn("diagnostic_msgs.msg", imports)
            self.assertFalse(any(name.startswith("data_msgs") for name in imports))
            self.assertTrue(self.has_force_kill)

    def test_source_matches_local_backup(self):
        if self.is_baseline and BACKUP_PATH.is_file():
            self.assertEqual(SOURCE_PATH.read_bytes(), BACKUP_PATH.read_bytes())
        elif not self.is_baseline:
            self.assertTrue(self.has_force_kill)
            if BACKUP_PATH.is_file():
                self.assertNotEqual(SOURCE_PATH.read_bytes(), BACKUP_PATH.read_bytes())

    def test_five_field_config_and_defaults(self):
        with tempfile.TemporaryDirectory(prefix="bk-config-", dir="/tmp") as home:
            config_path = Path(home) / self.module.EXTEND_LAUNCH_CONFIG_NAME
            config_path.write_text(
                '"defaults", `/usr/bin/sleep 60`\n'
                '"unchecked", `/usr/bin/sleep 60`, true, true, false\n'
                '"quiet", `/usr/bin/sleep 60`, false, true, true\n',
                encoding="utf-8",
            )
            holder = SimpleNamespace(
                home=home,
                extend_launch_config_info=self.module.ConfigInfo(),
                extend_launch_dict={},
                add_extend_id=lambda launch_id: True,
            )
            self.module.LaunchControlRosNode.load_extend_launch_config(holder)
            self.assertEqual(set(holder.extend_launch_dict), {"defaults", "unchecked", "quiet"})
            defaults = holder.extend_launch_dict["defaults"]
            self.assertEqual(defaults.get_cmd_raw(), ["/usr/bin/sleep", "60"])
            self.assertTrue(defaults.get_enable_output())
            self.assertFalse(defaults.get_multi_log_mode())
            self.assertTrue(defaults.get_check_status())
            unchecked = holder.extend_launch_dict["unchecked"]
            self.assertTrue(unchecked.get_enable_output())
            self.assertTrue(unchecked.get_multi_log_mode())
            self.assertFalse(unchecked.get_check_status())
            quiet = holder.extend_launch_dict["quiet"]
            self.assertFalse(quiet.get_enable_output())
            self.assertFalse(quiet.get_multi_log_mode())
            self.assertTrue(quiet.get_check_status())
            if self.has_force_kill:
                self.assertTrue(
                    all(not process.get_force_kill() for process in holder.extend_launch_dict.values())
                )
            self.assertTrue(all(not process.exist for process in holder.extend_launch_dict.values()))
            self.assertEqual(
                holder.extend_launch_config_info.last_config_time, config_path.stat().st_mtime
            )

    def test_sixth_field_force_kill(self):
        if not self.has_force_kill:
            self.assertTrue(self.is_baseline)
            return
        with tempfile.TemporaryDirectory(prefix="bk-force-kill-", dir="/tmp") as home:
            config_path = Path(home) / self.module.EXTEND_LAUNCH_CONFIG_NAME
            config_path.write_text(
                '"forced", `/usr/bin/sleep 60`, false, false, false, true\n'
                '"graceful", `/usr/bin/sleep 60`, false, false, true, false\n',
                encoding="utf-8",
            )
            holder = SimpleNamespace(
                home=home,
                extend_launch_config_info=self.module.ConfigInfo(),
                extend_launch_dict={},
                add_extend_id=lambda launch_id: True,
            )
            self.module.LaunchControlRosNode.load_extend_launch_config(holder)
            self.assertEqual(set(holder.extend_launch_dict), {"forced", "graceful"})
            self.assertTrue(holder.extend_launch_dict["forced"].get_force_kill())
            self.assertFalse(holder.extend_launch_dict["forced"].get_check_status())
            self.assertFalse(holder.extend_launch_dict["graceful"].get_force_kill())
            self.assertTrue(holder.extend_launch_dict["graceful"].get_check_status())

    def test_publish_status_without_node(self):
        status_publisher = FakePublisher()
        diagnostic_publisher = FakePublisher()
        stamp = None
        if hasattr(self.module, "DiagnosticArray"):
            stamp = self.module.DiagnosticArray().header.stamp
            stamp.sec = 123
            stamp.nanosec = 456
        holder = SimpleNamespace(
            extend_launch_dict={
                "stopped": SimpleNamespace(is_run=lambda: False, get_check_status=lambda: True),
                "unchecked": SimpleNamespace(is_run=lambda: False, get_check_status=lambda: False),
                "running": SimpleNamespace(is_run=lambda: True, get_check_status=lambda: True),
            },
            launch_status_pub=status_publisher,
            launch_diagnostic_pub=diagnostic_publisher,
            get_clock=lambda: SimpleNamespace(
                now=lambda: SimpleNamespace(to_msg=lambda: stamp)
            ),
        )
        self.module.LaunchControlRosNode.publish_status(holder)
        messages = status_publisher.messages
        self.assertEqual(len(messages), 1)
        self.assertEqual(list(messages[0].launch_id_list), ["stopped", "unchecked", "running"])
        self.assertEqual(list(messages[0].launch_status), [False, True, True])
        if self.is_baseline:
            self.assertEqual(diagnostic_publisher.messages, [])
        else:
            self.assertEqual(len(diagnostic_publisher.messages), 1)
            diagnostic = diagnostic_publisher.messages[0]
            self.assertIsInstance(diagnostic, self.module.DiagnosticArray)
            self.assertEqual(diagnostic.header.stamp, stamp)
            self.assertEqual([status.name for status in diagnostic.status],
                             ["stopped", "unchecked", "running"])
            self.assertEqual(
                [[(value.key, value.value) for value in status.values]
                 for status in diagnostic.status],
                [[("launch_status", "false")], [("launch_status", "true")],
                 [("launch_status", "true")]],
            )

    def test_missing_executable_failure(self):
        if not self.has_force_kill:
            self.assertTrue(self.is_baseline)
            return
        with tempfile.TemporaryDirectory(prefix="bk-missing-executable-", dir="/tmp") as home:
            process = self.module.LaunchProcess(
                cmd_raw=[str(Path(home) / "missing-executable")], enable_output=False
            )
            try:
                with patch.object(self.module, "write_launch_log_and_print") as log:
                    self.assertIs(process.launch(), False)
                    log.assert_called_once()
                    self.assertIn("failed", log.call_args.args[0])
                self.assertFalse(process.exist)
                self.assertFalse(process.run)
                self.assertFalse(process.load)
                self.assertFalse(process.is_run())
                self.assertEqual(process.status(), self.module.LAUNCH_STATUS["NOT_EXIST"])
            finally:
                process.reset()

    def test_own_sleep_launch_and_shutdown(self):
        process = self.module.LaunchProcess(
            cmd_raw=["/usr/bin/sleep", "60"], enable_output=False
        )
        child = None
        try:
            self.assertTrue(process.launch())
            child = process.child
            self.assertIsNone(child.poll())
            self.assertTrue(process.is_run())
            self.assertFalse(process.launch())
            self.assertTrue(process.shutdown())
            self.assertIsNotNone(child.poll())
            self.assertFalse(process.is_run())
            self.assertFalse(process.run)
            self.assertFalse(process.load)
        finally:
            if child is None:
                child = getattr(process, "child", None)
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            process.reset()


if __name__ == "__main__":
    unittest.main()
