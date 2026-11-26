from dataclasses import replace
from contextlib import contextmanager
import copy
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

import can_supervisor as can


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.config = can.load_config(Path(__file__).with_name("can_bus.json"))
        self.links = {
            device.name: can.Observation(device.name, index, "can", ("UP",), device.bitrate, "ERROR-ACTIVE", device.identity)
            for index, device in enumerate(self.config.devices, 1)
        }
        self.runner = mock.Mock()
        self.stop = mock.Mock()
        self.stop.is_set.return_value = False
        self.stop.wait.return_value = True
        self.messages = []
        self.supervisor = can.Supervisor(self.config, lambda: dict(self.links), self.runner, self.stop,
                                         lambda level, message: self.messages.append((level, message)))

    def test_healthy_interfaces_never_mutated(self):
        self.assertEqual(self.supervisor.run(), 0)
        self.runner.assert_not_called()
        ready = [index for index, item in enumerate(self.messages) if item[0] == "READY"]
        self.assertEqual(ready, [len(self.config.devices) + 1])
        self.assertEqual(self.messages[0], ("INIT", can.format_config_settings(self.config)))
        self.assertEqual(
            self.messages[1:1 + len(self.config.devices)],
            [("INIT", can.format_configured_device(device, "already available; unchanged")) for device in self.config.devices],
        )
        self.assertEqual(self.messages[ready[0]][1], "All required CAN interfaces activated as configured")

    def test_missing_at_startup_prevents_all_writes(self):
        self.links.pop("can_head")
        self.links["can_torso"] = replace(self.links["can_torso"], flags=())
        with self.assertRaises(can.CanFailure) as raised:
            self.supervisor.run()
        self.assertEqual(raised.exception.code, 3)
        lines = str(raised.exception).splitlines()
        head = next(line for line in lines if line.startswith("can_head "))
        torso = next(line for line in lines if line.startswith("can_torso "))
        imu = next(line for line in lines if line.startswith("can_chassis_imu "))
        self.assertIn("hardware matches=0", head)
        self.assertNotIn("identified", head)
        self.assertIn("identified; not activated", torso)
        self.assertIn("identified; already available; unchanged", imu)
        self.runner.assert_not_called()

    def test_runtime_missing_exits_without_repair(self):
        def wait(_):
            self.links.pop("can_head")
            return False
        self.stop.wait.side_effect = wait
        with self.assertRaises(can.CanFailure) as raised:
            self.supervisor.run()
        self.assertEqual(raised.exception.code, 5)
        self.assertNotIn("identified; not activated", str(raised.exception))
        self.runner.assert_not_called()

    def test_target_collision_prevents_writes(self):
        device = self.config.devices[0]
        self.links["renamed"] = replace(self.links[device.name], name="renamed")
        self.links[device.name] = can.Observation(device.name, 99, "vcan", ("UP",))
        with self.assertRaises(can.CanFailure):
            self.supervisor.activate()
        self.runner.assert_not_called()

    def test_generation_change_exits(self):
        baseline = dict(self.links)
        self.links["can_head"] = replace(self.links["can_head"], ifindex=100)
        with self.assertRaisesRegex(can.CanFailure, "generation changed"):
            self.supervisor.check_available(baseline)

    def test_error_passive_warns_but_does_not_exit(self):
        self.links["can_head"] = replace(self.links["can_head"], state="ERROR-PASSIVE")
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(sum(level == "WARN" for level, _ in self.messages), 1)
        self.runner.assert_not_called()

    def apply_command(self, arguments, code=4):
        name, operation = arguments[3], arguments[4:]
        observation = self.links[name]
        if operation == ["down"]:
            self.links[name] = replace(observation, flags=(), state="STOPPED")
        elif operation == ["up"]:
            self.links[name] = replace(observation, flags=("UP",), state="ERROR-ACTIVE")
        elif operation[0] == "name":
            self.links.pop(name)
            self.links[operation[1]] = replace(observation, name=operation[1])
        elif operation[:3] == ["type", "can", "bitrate"]:
            self.links[name] = replace(observation, bitrate=int(operation[3]))
        else:
            self.fail("Unexpected mutation: " + repr(arguments))

    def test_only_faulty_interface_initialized(self):
        device = self.config.devices[-1]
        self.links[device.name] = replace(self.links[device.name], flags=(), bitrate=None, state="STOPPED")
        self.runner.side_effect = self.apply_command
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.runner.call_count, 3)
        for call in self.runner.call_args_list:
            self.assertEqual(call.args[0][3], device.name)

    def test_non_can_prefix_renamed_once(self):
        device = self.config.devices[-1]
        self.links["adapter9"] = replace(self.links.pop(device.name), name="adapter9")
        self.runner.side_effect = self.apply_command
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.runner.call_count, 4)
        self.assertIn(device.name, self.links)
        self.assertNotIn("adapter9", self.links)

    def test_runtime_faults_never_repaired(self):
        healthy = self.links["can_head"]
        for change in ({"flags": ()}, {"bitrate": 250000}, {"state": "BUS-OFF"},
                       {"state": "STOPPED"}, {"state": "SLEEPING"}, {"state": "UNKNOWN"},
                       {"identity": ("0000:99:00.0", "0x0")}, {"kind": "vcan"}, {"can_fd": True}):
            with self.subTest(change=change):
                self.links["can_head"] = replace(healthy, **change)
                with self.assertRaises(can.CanFailure) as raised:
                    self.supervisor.check_available()
                self.assertEqual(raised.exception.code, 5)
                self.runner.assert_not_called()

    def test_unknown_state_at_startup_prevents_writes(self):
        self.links["can_head"] = replace(self.links["can_head"], state="UNKNOWN")
        with self.assertRaises(can.CanFailure):
            self.supervisor.activate()
        self.runner.assert_not_called()

    def test_bus_off_startup_single_activation(self):
        self.links["can_head"] = replace(self.links["can_head"], state="BUS-OFF")
        self.runner.side_effect = self.apply_command
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.runner.call_count, 3)
        head = next(device for device in self.config.devices if device.name == "can_head")
        line = ("INIT", can.format_configured_device(head, "activated"))
        self.assertIn(line, self.messages)
        self.assertLess(
            self.messages.index(line),
            next(index for index, item in enumerate(self.messages) if item[0] == "READY"),
        )

    def test_failed_activation_is_not_retried(self):
        self.links["can_head"] = replace(self.links["can_head"], flags=())
        self.runner.side_effect = can.CanFailure(4, "operation not permitted")
        with self.assertRaisesRegex(can.CanFailure, "operation not permitted"):
            self.supervisor.run()
        self.assertEqual(self.runner.call_count, 1)
        self.assertFalse(any(level == "READY" for level, _ in self.messages))

    def test_successful_commands_require_fresh_verification(self):
        self.links["can_head"] = replace(self.links["can_head"], flags=())
        with self.assertRaises(can.CanFailure) as raised:
            self.supervisor.run()
        self.assertEqual(raised.exception.code, 4)
        self.assertEqual(self.runner.call_count, 3)

    def test_identity_race_before_mutation_aborts(self):
        self.links["can_head"] = replace(self.links["can_head"], flags=())
        initial = dict(self.links)
        changed = dict(self.links)
        changed["can_head"] = replace(changed["can_head"], ifindex=100)
        self.supervisor.observe = mock.Mock(side_effect=[initial, changed])
        with self.assertRaisesRegex(can.CanFailure, "identity changed"):
            self.supervisor.activate()
        self.runner.assert_not_called()

    def test_safe_name_rollback(self):
        self.links["adapter9"] = replace(self.links.pop("can_head"), name="adapter9")
        def runner(arguments, code=4):
            if arguments[4:7] == ["type", "can", "bitrate"]:
                raise can.CanFailure(4, "bitrate rejected")
            self.apply_command(arguments, code)
        self.runner.side_effect = runner
        with self.assertRaisesRegex(can.CanFailure, "bitrate rejected") as raised:
            self.supervisor.run()
        self.assertIn("adapter9", self.links)
        self.assertNotIn("can_head", self.links)
        self.assertEqual(self.links["adapter9"].flags, ())
        self.assertIn("activation incomplete; old name restored", str(raised.exception))
        self.assertTrue(any("restored old name" in message for _, message in self.messages))

    def test_failed_rollback_preserves_original_failure(self):
        self.links["adapter9"] = replace(self.links.pop("can_head"), name="adapter9")
        def runner(arguments, code=4):
            if arguments[4:7] == ["type", "can", "bitrate"]:
                raise can.CanFailure(4, "bitrate rejected")
            if arguments[4:] == ["name", "adapter9"]:
                raise can.CanFailure(4, "rollback rejected")
            self.apply_command(arguments, code)
        self.runner.side_effect = runner
        with self.assertRaisesRegex(can.CanFailure, "bitrate rejected") as raised:
            self.supervisor.run()
        self.assertIn("can_head", self.links)
        self.assertIn("activation incomplete; old name not restored", str(raised.exception))
        self.assertTrue(any("rollback failed" in message for _, message in self.messages))

    def test_warning_changes_are_not_repeated_from_old_snapshot(self):
        changes = iter(["ERROR-PASSIVE", "ERROR-PASSIVE", "ERROR-ACTIVE", "ERROR-PASSIVE", None])
        def wait(_):
            state = next(changes)
            if state is None:
                return True
            self.links["can_head"] = replace(self.links["can_head"], state=state)
            return False
        self.stop.wait.side_effect = wait
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(sum(level == "WARN" for level, _ in self.messages), 2)

    def test_observation_error_during_monitor_is_fatal(self):
        self.supervisor.observe = mock.Mock(side_effect=[dict(self.links), dict(self.links), can.CanFailure(6, "ip timeout")])
        self.stop.wait.return_value = False
        with self.assertRaisesRegex(can.CanFailure, "ip timeout"):
            self.supervisor.run()
        self.runner.assert_not_called()

    def test_activation_failure_reports_each_device(self):
        activated, failed = self.config.devices[1], self.config.devices[2]
        self.links[activated.name] = replace(self.links[activated.name], flags=(), bitrate=None, state="STOPPED")
        self.links[failed.name] = replace(self.links[failed.name], flags=(), bitrate=None, state="STOPPED")

        def runner(arguments, code=4):
            if arguments[3] == failed.name:
                raise can.CanFailure(4, "second interface rejected")
            self.apply_command(arguments, code)

        self.runner.side_effect = runner
        with self.assertRaises(can.CanFailure) as raised:
            self.supervisor.run()
        self.assertEqual(raised.exception.code, 4)
        summary = str(raised.exception).split("second interface rejected\n", 1)[1]
        expected = [
            f"{self.config.devices[0].name}: already available; unchanged",
            f"{activated.name}: activated",
            f"{failed.name}: activation incomplete",
        ]
        expected.extend(f"{device.name}: not reached; not activated" for device in self.config.devices[3:])
        self.assertEqual(summary.splitlines(), expected)

    def test_duplicate_hardware_identity_prevents_writes(self):
        self.links["extra"] = replace(self.links["can_head"], name="extra", ifindex=90)
        with self.assertRaisesRegex(can.CanFailure, "hardware matches=2"):
            self.supervisor.run()
        self.runner.assert_not_called()

    def test_stop_requested_prevents_activation(self):
        self.stop.is_set.return_value = True
        self.assertEqual(self.supervisor.run(), 0)
        self.runner.assert_not_called()

    def test_stop_during_activation_prevents_further_writes(self):
        self.links["adapter9"] = replace(self.links.pop("can_head"), name="adapter9")
        def runner(arguments, code=4):
            self.apply_command(arguments, code)
            self.stop.is_set.return_value = True
        self.runner.side_effect = runner
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.runner.call_count, 1)
        self.assertIn("adapter9", self.links)
        self.assertEqual(self.links["adapter9"].flags, ())

    def test_stop_during_monitor_leaves_links_untouched(self):
        original = dict(self.links)
        def wait(_):
            self.stop.is_set.return_value = True
            return True
        self.stop.wait.side_effect = wait
        self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.links, original)
        self.runner.assert_not_called()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).with_name("can_bus.json")
        self.document = json.loads(self.path.read_text())

    def load(self, document):
        with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(document))):
            return can.load_config("unused")

    def test_six_exact_legacy_mappings(self):
        config = can.load_config(self.path)
        self.assertEqual([device.name for device in config.devices],
                         ["can_chassis_imu", "can_chassis", "can_right_arm", "can_torso", "can_left_arm", "can_head"])
        self.assertEqual([device.bitrate for device in config.devices], [500000, 500000, 1000000, 1000000, 1000000, 1000000])
        self.assertEqual([device.identity for device in config.devices],
                         [("0000:03:00.0", "0x0"), ("0000:03:00.0", "0x1"), ("0000:30:00.0", "0x0"),
                          ("0000:30:00.0", "0x1"), ("0000:31:00.0", "0x0"), ("0000:31:00.0", "0x1")])

    def test_invalid_fields_and_numbers(self):
        for field, value in (("name", "x" * 16), ("name", "../bad"), ("name", "中文"),
                             ("dev_id", True), ("dev_id", "-1"), ("bus_addr", "garbage"),
                             ("bitrate", True), ("bitrate", 0), ("bitrate", 1000001)):
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(self.document)
                document["devices"][0][field] = value
                with self.assertRaises(can.CanFailure) as raised:
                    self.load(document)
                self.assertEqual(raised.exception.code, 2)
        for field in ("poll_interval", "command_timeout"):
            for value in (True, 0, -1, float("nan"), float("inf"), 61, "1"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(can.CanFailure):
                        self.load(dict(self.document, **{field: value}))

    def test_unknown_duplicate_or_empty_config(self):
        duplicate_identity = copy.deepcopy(self.document)
        duplicate_identity["devices"][1]["dev_id"] = "0x0"
        duplicate_name = copy.deepcopy(self.document)
        duplicate_name["devices"][1]["name"] = duplicate_name["devices"][0]["name"]
        for document in ({}, [], dict(self.document, extra=True), dict(self.document, devices=[]),
                         duplicate_identity, duplicate_name):
            with self.assertRaises(can.CanFailure):
                self.load(document)
        with mock.patch("builtins.open", mock.mock_open(read_data='{"devices": [], "devices": []}')):
            with self.assertRaisesRegex(can.CanFailure, "Duplicate JSON key"):
                can.load_config("unused")

    def test_usb_and_decimal_port_id(self):
        document = copy.deepcopy(self.document)
        document["devices"][0].update(bus_addr="1-2.3:1.0", dev_id="00")
        self.assertEqual(self.load(document).devices[0].identity, ("1-2.3:1.0", "0x0"))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sysfs = self.root / "net"
        self.sysfs.mkdir()
        self.link = {"ifname": "adapter9", "ifindex": 7, "flags": ["UP"], "linkinfo": {
            "info_kind": "can", "info_data": {"state": "ERROR-ACTIVE", "bittiming": {"bitrate": 500000}}}}
        self.make_sysfs("adapter9", "0000:03:00.0", "0x0")

    def make_sysfs(self, name, address, dev_id):
        iface = self.sysfs / name
        iface.mkdir()
        (iface / "ifindex").write_text("7\n")
        (iface / "dev_id").write_text(dev_id + "\n")
        device = self.root / "devices" / address / "controller"
        device.mkdir(parents=True, exist_ok=True)
        (iface / "device").symlink_to(device)

    def read(self, links=None):
        runner = mock.Mock(return_value=json.dumps([self.link] if links is None else links))
        result = can.read_observations(runner, self.sysfs)
        self.assertEqual(runner.call_args.args[0], ["-details", "-json", "link", "show"])
        return result

    def test_pci_identity_without_can_prefix(self):
        self.assertEqual(self.read()["adapter9"].identity, ("0000:03:00.0", "0x0"))

    def test_usb_interface_ancestor_identity(self):
        self.link["ifname"] = "usb_adapter"
        self.make_sysfs("usb_adapter", "1-2.3:1.0", "01")
        self.assertEqual(self.read()["usb_adapter"].identity, ("1-2.3:1.0", "0x1"))

    def test_fd_flags_and_capable_but_classic_controller(self):
        data = self.link["linkinfo"]["info_data"]
        data["dbittiming_const"] = {"brp_min": 1}
        data["ctrlmode"] = {"flags": []}
        self.assertFalse(self.read()["adapter9"].can_fd)
        for flags in (["FD"], {"flags": ["FD"]}):
            data["ctrlmode"] = flags
            self.assertTrue(self.read()["adapter9"].can_fd)

    def test_ifindex_race_and_missing_sysfs_are_errors(self):
        (self.sysfs / "adapter9" / "ifindex").write_text("9")
        with self.assertRaises(can.CanFailure) as raised:
            self.read()
        self.assertEqual(raised.exception.code, 6)
        (self.sysfs / "adapter9" / "ifindex").unlink()
        with self.assertRaises(can.CanFailure):
            self.read()

    def test_malformed_json_links_fail_closed(self):
        for links in ({}, [None], [self.link, self.link], [{"ifname": "can0"}],
                      [dict(self.link, flags=None)], [dict(self.link, ifindex=True)],
                      [dict(self.link, ifname="../bad")], [dict(self.link, linkinfo=[])]):
            with self.subTest(links=links):
                with self.assertRaises(can.CanFailure) as raised:
                    self.read(links)
                self.assertEqual(raised.exception.code, 6)

    def test_nonphysical_links_are_not_hardware_matches(self):
        self.link["linkinfo"]["info_kind"] = "vcan"
        observation = self.read()["adapter9"]
        self.assertIsNone(observation.identity)


class ProcessTests(unittest.TestCase):
    def test_runner_argument_list_timeout_and_no_shell(self):
        execute = mock.Mock(return_value=mock.Mock(returncode=0, stdout="[]"))
        self.assertEqual(can.IpRunner("/usr/sbin/ip", 3, execute)(["-json", "link", "show"]), "[]")
        self.assertEqual(execute.call_args.args[0], ["/usr/sbin/ip", "-json", "link", "show"])
        self.assertEqual(execute.call_args.kwargs["timeout"], 3)
        self.assertNotIn("shell", execute.call_args.kwargs)

    def test_runner_timeout_and_stderr_failure_codes(self):
        for failure in (subprocess.TimeoutExpired("ip", 3), OSError("missing executable")):
            runner = can.IpRunner("/usr/sbin/ip", 3, mock.Mock(side_effect=failure))
            with self.assertRaises(can.CanFailure) as raised:
                runner(["link", "show"])
            self.assertEqual(raised.exception.code, 6)
        execute = mock.Mock(return_value=mock.Mock(returncode=1, stderr="RTNETLINK denied"))
        with self.assertRaisesRegex(can.CanFailure, "RTNETLINK denied") as raised:
            can.IpRunner("/usr/sbin/ip", 3, execute)(["link", "set"], code=4)
        self.assertEqual(raised.exception.code, 4)

    def test_single_instance_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "can.lock"
            with can.singleton_lock(path):
                with self.assertRaises(can.CanFailure) as raised:
                    with can.singleton_lock(path):
                        self.fail("Duplicate acquired lock")
                self.assertEqual(raised.exception.code, 7)
            with can.singleton_lock(path):
                pass
            link = Path(directory) / "symlink.lock"
            link.symlink_to(path)
            with self.assertRaises(can.CanFailure):
                with can.singleton_lock(link):
                    pass

    def test_check_config_requires_no_ip_or_privilege(self):
        with mock.patch.object(can, "find_ip", side_effect=AssertionError("must not query ip")):
            with mock.patch.object(can, "log"):
                self.assertEqual(can.main(["--check-config"]), 0)

    def test_activation_requires_root_before_query(self):
        with mock.patch.object(can.os, "geteuid", return_value=1000):
            with mock.patch.object(can, "find_ip", side_effect=AssertionError("must not query ip")):
                with mock.patch.object(can, "log") as emit:
                    self.assertEqual(can.main([]), 7)
        self.assertIn("root", emit.call_args.args[1])

    def test_main_returns_failure_and_flushes_stderr(self):
        with mock.patch.object(can.os, "geteuid", return_value=0):
            with mock.patch.object(can, "find_ip", return_value="/usr/sbin/ip"):
                with mock.patch.object(can, "read_observations", side_effect=can.CanFailure(6, "bad ip JSON")):
                    with mock.patch("sys.stderr", new_callable=io.StringIO) as output:
                        self.assertEqual(can.main(["--dry-run"]), 6)
        self.assertIn("exit=6", output.getvalue())
        self.assertIn("bad ip JSON", output.getvalue())

    def test_dry_run_never_mutates_or_locks(self):
        config = can.load_config(Path(__file__).with_name("can_bus.json"))
        links = {device.name: can.Observation(device.name, index, "can", (), None, "STOPPED", device.identity)
                 for index, device in enumerate(config.devices, 1)}
        with mock.patch.object(can, "find_ip", return_value="/usr/sbin/ip"):
            with mock.patch.object(can, "read_observations", return_value=links):
                with mock.patch.object(can, "singleton_lock", side_effect=AssertionError("no locks in dry run")):
                    with mock.patch.object(can, "IpRunner") as runner, mock.patch.object(can, "log"):
                        self.assertEqual(can.main(["--dry-run"]), 0)
                        runner.return_value.assert_not_called()

    def test_signal_stops_and_restores_handlers(self):
        config = can.load_config(Path(__file__).with_name("can_bus.json"))
        links = {device.name: can.Observation(device.name, index, "can", ("UP",), device.bitrate, "ERROR-ACTIVE", device.identity)
                 for index, device in enumerate(config.devices, 1)}
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous = signal.getsignal(signum)
            @contextmanager
            def stop_on_entry():
                os.kill(os.getpid(), signum)
                yield
            with mock.patch.object(can.os, "geteuid", return_value=0), mock.patch.object(can, "log"):
                with mock.patch.object(can, "find_ip", return_value="/usr/sbin/ip"):
                    with mock.patch.object(can, "read_observations", return_value=links):
                        with mock.patch.object(can, "singleton_lock", stop_on_entry):
                            self.assertEqual(can.main([]), 0)
            self.assertEqual(signal.getsignal(signum), previous)


class UninstallTests(unittest.TestCase):
    def test_active_python_instance_blocks_uninstall_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "can.lock"
            with can.singleton_lock(path):
                result = self.run_shell('check_trusted() { return 0; }\nacquire_instance_lock "$2/can.lock" true\n', directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("can_health is running", result.stderr)
            result = self.run_shell('check_trusted() { return 0; }\nacquire_instance_lock "$2/can.lock" true\nexec {UNINSTALL_LOCK_FD}<&-\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(path.exists())

    def test_lock_preview_creates_nothing_and_real_lock_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "can.lock"
            result = self.run_shell('acquire_instance_lock "$2/can.lock" true\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            result = self.run_shell('check_trusted() { return 0; }\nacquire_instance_lock "$2/can.lock" false\nexec {UNINSTALL_LOCK_FD}<&-\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def run_shell(self, body, directory):
        script = Path(__file__).with_name("uninstall_can_tools.sh")
        return subprocess.run(["/bin/bash", "-s", "--", str(script), str(directory)],
                              input='source "$1"\n' + body, text=True, capture_output=True, timeout=5)

    def test_help_and_unknown_argument(self):
        script = Path(__file__).with_name("uninstall_can_tools.sh")
        help_result = subprocess.run(["/bin/bash", str(script), "--help"], capture_output=True, text=True, timeout=5)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--purge", help_result.stdout)
        invalid = subprocess.run(["/bin/bash", str(script), "--unknown"], capture_output=True, text=True, timeout=5)
        self.assertEqual(invalid.returncode, 2)

    def test_preview_preserves_file_and_delete_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.py"
            path.write_text("fixture")
            result = self.run_shell('check_trusted() { return 0; }\nremove_file "$2/program.py" true\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Would remove", result.stdout)
            self.assertTrue(path.exists())
            result = self.run_shell('check_trusted() { return 0; }\nremove_file "$2/program.py" false\nremove_file "$2/program.py" false\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            self.assertIn("Already absent", result.stdout)

    def test_symlink_is_rejected_and_target_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("keep")
            (Path(directory) / "program.py").symlink_to(target)
            result = self.run_shell('remove_file "$2/program.py" false\n', directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing symlink", result.stderr)
            self.assertEqual(target.read_text(), "keep")

    def test_nonempty_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "installed"
            target.mkdir()
            (target / "unrelated").write_text("keep")
            result = self.run_shell('remove_empty_directory "$2/installed" false\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((target / "unrelated").exists())
            (target / "unrelated").unlink()
            result = self.run_shell('remove_empty_directory "$2/installed" false\n', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
