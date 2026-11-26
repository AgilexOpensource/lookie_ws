import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "launch_control/scripts/launch_control.py"


class RobotConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("robot_config_under_test", SOURCE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load launch_control module")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_command_substitution_rules(self):
        spaced, error = self.module.expand_robot_config_substitutions("$(echo hello world)")
        self.assertIsNone(error)
        self.assertEqual(spaced, "hello world")

        mixed, error = self.module.expand_robot_config_substitutions('$(echo hello)/share')
        self.assertIsNone(error)
        self.assertEqual(mixed, "hello/share")

        quoted, error = self.module.expand_robot_config_substitutions('"$(echo quoted value)"')
        self.assertIsNone(error)
        self.assertEqual(quoted, "quoted value")

        literal, error = self.module.expand_robot_config_substitutions("'$(echo hi)'")
        self.assertIsNone(error)
        self.assertEqual(literal, "$(echo hi)")

        failed, error = self.module.expand_robot_config_substitutions("$(false)")
        self.assertIsNone(failed)
        self.assertIn("command substitution failed", error)

        unclosed, error = self.module.expand_robot_config_substitutions("$(echo hi")
        self.assertIsNone(unclosed)
        self.assertEqual(error, "unclosed command substitution")

        timed_out, error = self.module.expand_robot_config_substitutions("$(sleep 1)", timeout=0.2)
        self.assertIsNone(timed_out)
        self.assertIn("timed out", error)

        env = {"ROS_VERSION": "humble"}
        path, error = self.module.expand_robot_config_substitutions(
            "$ROS_VERSION/config/1.yaml", env=env
        )
        self.assertIsNone(error)
        self.assertEqual(path, "humble/config/1.yaml")

        braced, error = self.module.expand_robot_config_substitutions(
            '"${ROS_VERSION}/config/1.yaml"', env=env
        )
        self.assertIsNone(error)
        self.assertEqual(braced, "humble/config/1.yaml")

        quoted_name, error = self.module.expand_robot_config_substitutions(
            "'$ROS_VERSION/config/1.yaml'", env=env
        )
        self.assertIsNone(error)
        self.assertEqual(quoted_name, "$ROS_VERSION/config/1.yaml")

        dollars, error = self.module.expand_robot_config_substitutions("$$", env=env)
        self.assertIsNone(error)
        self.assertEqual(dollars, "$$")

        unset, error = self.module.expand_robot_config_substitutions(
            "$ROS_VERSION/config/1.yaml", env={}
        )
        self.assertIsNone(unset)
        self.assertEqual(error, "unset variable ROS_VERSION")

    def test_load_keeps_plain_values_and_skips_failed_or_startup_commands(self):
        keys = [
            "LC_TEST_PLAIN",
            "LC_TEST_SPACED",
            "LC_TEST_MIXED",
            "LC_TEST_QUOTED",
            "LC_TEST_LITERAL",
            "LC_TEST_FROM_EARLIER",
            "LC_TEST_FAIL",
            "LC_TEST_OPEN",
        ]
        previous = {key: os.environ.pop(key, None) for key in keys}
        previous_path = os.environ.get("PATH")
        os.environ["LC_TEST_FAIL"] = "old"
        marker = None
        try:
            with tempfile.TemporaryDirectory(prefix="robot-config-", dir="/tmp") as home:
                marker = Path(home) / "startup-marker"
                config_path = Path(home) / self.module.ROBOT_CONFIG_NAME
                config_path.write_text(
                    "\n".join([
                        'export LC_TEST_PLAIN="333"',
                        "export LC_TEST_SPACED=$(echo hello world)",
                        "export LC_TEST_MIXED=$(echo hello)/share",
                        'export LC_TEST_QUOTED="$(echo quoted value)"',
                        "export LC_TEST_LITERAL='$(echo hi)'",
                        'export LC_TEST_FROM_EARLIER=$(echo "$LC_TEST_SPACED"-tail)',
                        "export LC_TEST_FAIL=$(false)",
                        f"export PATH=$(touch {marker})",
                        "export LC_TEST_OPEN=$(echo hi",
                    ]) + "\n",
                    encoding="utf-8",
                )
                holder = SimpleNamespace(
                    home=home,
                    robot_config_info=self.module.ConfigInfo(),
                    robot_config_dict={"LC_TEST_FAIL": "old"},
                    robot_config_description_dict={},
                )
                logs = []
                with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
                    self.module.LaunchControlRosNode.load_robot_config(holder)

                self.assertEqual(holder.robot_config_dict["LC_TEST_PLAIN"], "333")
                self.assertEqual(holder.robot_config_dict["LC_TEST_SPACED"], "hello world")
                self.assertEqual(holder.robot_config_dict["LC_TEST_MIXED"], "hello/share")
                self.assertEqual(holder.robot_config_dict["LC_TEST_QUOTED"], "quoted value")
                self.assertEqual(holder.robot_config_dict["LC_TEST_LITERAL"], "$(echo hi)")
                self.assertEqual(holder.robot_config_dict["LC_TEST_FROM_EARLIER"], "hello world-tail")
                self.assertEqual(holder.robot_config_dict["LC_TEST_FAIL"], "old")
                self.assertEqual(os.environ["LC_TEST_FAIL"], "old")
                self.assertNotIn("LC_TEST_OPEN", holder.robot_config_dict)
                self.assertFalse(marker.exists())
                self.assertNotIn("PATH", holder.robot_config_dict)
                self.assertTrue(any("Ignoring startup-only variable PATH" in message for message in logs))
                self.assertTrue(any("invalid robot config value for 'LC_TEST_FAIL'" in message for message in logs))
                self.assertTrue(any("invalid robot config value for 'LC_TEST_OPEN'" in message for message in logs))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if previous_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous_path

    def test_load_expands_environment_references_without_replacing_unset(self):
        keys = ["LC_TEST_ROS_VERSION", "LC_TEST_AAABBB", "LC_TEST_MISSING"]
        previous = {key: os.environ.pop(key, None) for key in keys}
        os.environ["LC_TEST_AAABBB"] = "old-path"
        os.environ["LC_TEST_MISSING"] = "keep-me"
        try:
            with tempfile.TemporaryDirectory(prefix="robot-config-ref-", dir="/tmp") as home:
                config_path = Path(home) / self.module.ROBOT_CONFIG_NAME
                config_path.write_text(
                    "\n".join([
                        "export LC_TEST_ROS_VERSION=humble",
                        "export LC_TEST_AAABBB=$LC_TEST_ROS_VERSION/config/1.yaml",
                        "export LC_TEST_MISSING=$LC_TEST_NOT_SET/config/1.yaml",
                    ]) + "\n",
                    encoding="utf-8",
                )
                holder = SimpleNamespace(
                    home=home,
                    robot_config_info=self.module.ConfigInfo(),
                    robot_config_dict={
                        "LC_TEST_AAABBB": "old-path",
                        "LC_TEST_MISSING": "keep-me",
                    },
                    robot_config_description_dict={},
                )
                logs = []
                with patch.object(self.module, "write_launch_log_and_print", side_effect=logs.append):
                    self.module.LaunchControlRosNode.load_robot_config(holder)
                self.assertEqual(holder.robot_config_dict["LC_TEST_AAABBB"], "humble/config/1.yaml")
                self.assertEqual(os.environ["LC_TEST_AAABBB"], "humble/config/1.yaml")
                self.assertEqual(holder.robot_config_dict["LC_TEST_MISSING"], "keep-me")
                self.assertEqual(os.environ["LC_TEST_MISSING"], "keep-me")
                self.assertTrue(any("unset variable LC_TEST_NOT_SET" in message for message in logs))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
