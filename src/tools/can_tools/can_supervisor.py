#!/usr/bin/python3
"""Activate required physical CAN links once, then exit on loss of availability."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading


PCI_ADDRESS = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
USB_ADDRESS = re.compile(r"[0-9]+-[0-9]+(?:\.[0-9]+)*:[0-9]+\.[0-9]+")
IFACE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}")
ALLOWED_STATES = {"ERROR-ACTIVE", "ERROR-WARNING", "ERROR-PASSIVE"}
KNOWN_STATES = ALLOWED_STATES | {"BUS-OFF", "STOPPED", "SLEEPING"}
LOCK_PATH = Path("/run/lock/can-health.lock")


class CanFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class StopRequested(Exception):
    pass


@dataclass(frozen=True)
class DeviceConfig:
    bus_addr: str
    dev_id: str
    name: str
    bitrate: int

    @property
    def identity(self):
        return self.bus_addr, self.dev_id


@dataclass(frozen=True)
class Config:
    devices: tuple
    poll_interval: float = 1.0
    command_timeout: float = 3.0


@dataclass(frozen=True)
class Observation:
    name: str
    ifindex: int
    kind: str
    flags: tuple
    bitrate: object = None
    state: str = ""
    identity: object = None
    can_fd: bool = False


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def normalize_dev_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", value):
        raise ValueError("dev_id must be a decimal or hexadecimal string")
    return hex(int(value, 16 if value.lower().startswith("0x") else 10))


def load_config(path):
    try:
        with open(path, encoding="utf-8") as stream:
            document = json.load(stream, object_pairs_hook=unique_object)
        if not isinstance(document, dict) or set(document) != {"devices", "poll_interval", "command_timeout"}:
            raise ValueError("Root requires exactly devices, poll_interval and command_timeout")
        for field in ("poll_interval", "command_timeout"):
            value = document[field]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 60:
                raise ValueError(field + " must be a finite number in (0, 60]")
        entries = document["devices"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("devices must be a non-empty list")
        devices, identities, names = [], set(), set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"bus_addr", "dev_id", "name", "bitrate"}:
                raise ValueError("Each device requires bus_addr, dev_id, name and bitrate")
            address, name, bitrate = entry["bus_addr"], entry["name"], entry["bitrate"]
            if not isinstance(address, str) or not (PCI_ADDRESS.fullmatch(address) or USB_ADDRESS.fullmatch(address)):
                raise ValueError("Invalid physical bus address: " + str(address))
            if not isinstance(name, str) or not IFACE_NAME.fullmatch(name):
                raise ValueError("Invalid interface name: " + str(name))
            if type(bitrate) is not int or not 0 < bitrate <= 1000000:
                raise ValueError(name + ": classic CAN bitrate must be in [1, 1000000]")
            device = DeviceConfig(address.lower(), normalize_dev_id(entry["dev_id"]), name, bitrate)
            if device.identity in identities or name in names:
                raise ValueError("Duplicate hardware identity or target name: " + name)
            identities.add(device.identity)
            names.add(name)
            devices.append(device)
        return Config(tuple(devices), float(document["poll_interval"]), float(document["command_timeout"]))
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        raise CanFailure(2, "Cannot load configuration: " + str(exc)) from exc


def find_ip():
    for candidate in ("/usr/sbin/ip", "/sbin/ip", "/usr/bin/ip", "/bin/ip"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise CanFailure(6, "iproute2 is required; no system ip executable found")


class IpRunner:
    def __init__(self, command, timeout, run=subprocess.run):
        self.command, self.timeout, self.run = command, timeout, run

    def __call__(self, arguments, code=6):
        try:
            result = self.run(
                [self.command, *arguments], capture_output=True, text=True,
                check=False, timeout=self.timeout, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CanFailure(code, "ip " + " ".join(arguments) + ": " + str(exc)) from exc
        if result.returncode:
            raise CanFailure(code, "ip " + " ".join(arguments) + ": " + result.stderr.strip()[:1000])
        return result.stdout


def read_identity(root, name, ifindex):
    iface = root / name
    if int((iface / "ifindex").read_text().strip()) != ifindex:
        raise ValueError(name + ": ifindex changed during observation")
    device = iface / "device"
    if not device.is_symlink():
        return None
    real = device.resolve(strict=True)
    for ancestor in (real, *real.parents):
        if PCI_ADDRESS.fullmatch(ancestor.name) or USB_ADDRESS.fullmatch(ancestor.name):
            dev_id = normalize_dev_id((iface / "dev_id").read_text().strip())
            return ancestor.name.lower(), dev_id
    return None


def read_observations(runner, sysfs_root=Path("/sys/class/net")):
    output = runner(["-details", "-json", "link", "show"])
    try:
        links = json.loads(output, object_pairs_hook=unique_object)
        if not isinstance(links, list):
            raise ValueError("ip JSON root is not an array")
        observations, indexes = {}, set()
        for link in links:
            if not isinstance(link, dict):
                raise ValueError("Malformed link entry")
            name, ifindex, flags = link["ifname"], link["ifindex"], link["flags"]
            if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
                raise ValueError("Invalid observed interface name")
            if type(ifindex) is not int or ifindex <= 0 or ifindex in indexes or name in observations:
                raise ValueError("Duplicate or invalid interface identity")
            if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
                raise ValueError("Malformed link flags")
            info = link.get("linkinfo", {})
            kind = info.get("info_kind", "")
            data = info.get("info_data", {})
            if not isinstance(kind, str) or not isinstance(data, dict):
                raise ValueError("Malformed linkinfo")
            bitrate = data.get("bittiming", {}).get("bitrate") if kind == "can" else None
            state_value = data.get("state", "") if kind == "can" else ""
            if bitrate is not None and (type(bitrate) is not int or bitrate <= 0):
                raise ValueError("Invalid observed bitrate")
            if not isinstance(state_value, str):
                raise ValueError("Invalid CAN state")
            identity = read_identity(sysfs_root, name, ifindex) if kind == "can" else None
            ctrlmode = data.get("ctrlmode", [])
            if isinstance(ctrlmode, dict):
                ctrlmode = ctrlmode.get("flags", [])
            if not isinstance(ctrlmode, list):
                raise ValueError("Malformed CAN ctrlmode")
            fd = kind == "can" and "FD" in ctrlmode
            observations[name] = Observation(name, ifindex, kind, tuple(flags), bitrate, state_value, identity, fd)
            indexes.add(ifindex)
        return observations
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CanFailure(6, "Cannot obtain consistent CAN observations: " + str(exc)) from exc


def format_config_settings(config):
    return f"poll_interval={config.poll_interval} command_timeout={config.command_timeout}"


def format_configured_device(device, outcome):
    return f"{device.name} bus={device.bus_addr} dev_id={device.dev_id} bitrate={device.bitrate}: {outcome}"


def describe(device, observation):
    expected = f"{device.name} bus={device.bus_addr} dev_id={device.dev_id} bitrate={device.bitrate}"
    if observation is None:
        return expected + "; actual=ABSENT"
    return (expected + f"; actual={observation.name} ifindex={observation.ifindex}"
            + f" kind={observation.kind} flags={','.join(observation.flags)}"
            + f" bitrate={observation.bitrate} state={observation.state} identity={observation.identity}")


def validate_required(config, observations, code=3):
    matched, lines = {}, []
    failed = False
    for device in config.devices:
        matches = [item for item in observations.values() if item.kind == "can" and item.identity == device.identity]
        if len(matches) != 1:
            lines.append(describe(device, None) + f"; hardware matches={len(matches)}")
            failed = True
            continue
        observation = matches[0]
        occupied = observations.get(device.name)
        if occupied is not None and occupied.ifindex != observation.ifindex:
            lines.append(describe(device, observation) + "; target name is occupied; resolve manually")
            failed = True
        elif observation.can_fd or observation.state not in KNOWN_STATES:
            lines.append(describe(device, observation) + "; unsupported CAN FD or unknown controller state")
            failed = True
        else:
            matched[device.name] = observation
            if code == 3:
                if unavailable_reason(device, observation):
                    lines.append(describe(device, observation) + "; identified; not activated")
                else:
                    lines.append(describe(device, observation) + "; identified; already available; unchanged")
    if failed:
        raise CanFailure(code, "Required CAN validation failed:\n" + "\n".join(lines))
    return matched


def unavailable_reason(device, observation):
    if observation.name != device.name:
        return "interface name changed"
    if "UP" not in observation.flags:
        return "interface is DOWN"
    if observation.bitrate != device.bitrate:
        return "bitrate mismatch"
    if observation.state not in ALLOWED_STATES:
        return "controller unavailable"
    return ""


def log(level, message):
    stream = sys.stderr if level in ("FAIL", "WARN") else sys.stdout
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{timestamp} [{level}] {message}", file=stream, flush=True)


class Supervisor:
    def __init__(self, config, observe, runner, stop=None, emit=log):
        self.config, self.observe, self.runner = config, observe, runner
        self.stop = stop if stop is not None else threading.Event()
        self.emit = emit

    def check_stop(self):
        if self.stop.is_set():
            raise StopRequested()

    def guarded_command(self, device, ifindex, current_name, *arguments):
        self.check_stop()
        observation = validate_required(self.config, self.observe(), 4)[device.name]
        if observation.ifindex != ifindex or observation.name != current_name:
            raise CanFailure(4, describe(device, observation) + "; identity changed before mutation")
        self.check_stop()
        self.runner(["link", "set", "dev", current_name, *arguments], code=4)

    def activate(self):
        self.outcomes = {}
        try:
            self.check_stop()
            matched = validate_required(self.config, self.observe())
            for device in self.config.devices:
                observation = matched[device.name]
                if not unavailable_reason(device, observation):
                    self.outcomes[device.name] = "already available; unchanged"
                    continue
                self.outcomes[device.name] = "activation incomplete"
                old_name, current_name = observation.name, observation.name
                renamed = False
                try:
                    self.guarded_command(device, observation.ifindex, current_name, "down")
                    if current_name != device.name:
                        self.guarded_command(device, observation.ifindex, current_name, "name", device.name)
                        current_name, renamed = device.name, True
                    self.guarded_command(device, observation.ifindex, current_name, "type", "can", "bitrate", str(device.bitrate))
                    self.guarded_command(device, observation.ifindex, current_name, "up")
                    self.outcomes[device.name] = "activated"
                except CanFailure:
                    restored = False
                    if renamed and not self.stop.is_set():
                        restored = self.rollback_name(device, observation.ifindex, old_name)
                    if renamed:
                        self.outcomes[device.name] = (
                            "activation incomplete; old name restored" if restored
                            else "activation incomplete; old name not restored"
                        )
                    raise
            self.check_stop()
            return self.check_available(code=4)
        except CanFailure as exc:
            if exc.code != 4:
                raise
            raise CanFailure(exc.code, f"{exc}\n{self.activation_summary()}") from exc

    def activation_summary(self):
        lines = []
        for device in self.config.devices:
            outcome = self.outcomes.get(device.name, "not reached; not activated")
            lines.append(f"{device.name}: {outcome}")
        return "\n".join(lines)

    def rollback_name(self, device, ifindex, old_name):
        try:
            observations = self.observe()
            current = validate_required(self.config, observations, 4)[device.name]
            if current.ifindex != ifindex or current.name != device.name or old_name in observations:
                raise CanFailure(4, "Rollback identity/name safety check failed")
            self.guarded_command(device, ifindex, device.name, "down")
            self.guarded_command(device, ifindex, device.name, "name", old_name)
            self.emit("WARN", f"{device.name}: restored old name {old_name}; link remains down for manual inspection")
            return True
        except CanFailure as exc:
            self.emit("WARN", f"{device.name}: rollback failed, inspect residual link manually: {exc}")
            return False

    def check_available(self, baseline=None, code=5):
        self.check_stop()
        matched = validate_required(self.config, self.observe(), code)
        for device in self.config.devices:
            observation = matched[device.name]
            reason = unavailable_reason(device, observation)
            if baseline is not None and baseline[device.name].ifindex != observation.ifindex:
                reason = "interface generation changed; restart after inspecting the adapter"
            if reason:
                raise CanFailure(code, describe(device, observation) + "; " + reason)
        return matched

    def run(self):
        try:
            baseline = self.activate()
            self.emit("INIT", format_config_settings(self.config))
            for device in self.config.devices:
                self.emit("INIT", format_configured_device(device, self.outcomes[device.name]))
            self.emit("READY", "All required CAN interfaces activated as configured")
            warned = {}
            self.report_warnings(baseline, warned)
            while not self.stop.is_set():
                if self.stop.wait(self.config.poll_interval):
                    break
                baseline_now = self.check_available(baseline)
                self.report_warnings(baseline_now, warned)
            return 0
        except StopRequested:
            return 0

    def report_warnings(self, matched, warned):
        for device in self.config.devices:
            state_value = matched[device.name].state
            previous = warned.get(device.name)
            if state_value in ("ERROR-WARNING", "ERROR-PASSIVE") and state_value != previous:
                self.emit("WARN", describe(device, matched[device.name]) + "; inspect bus wiring/power; no automatic reset")
            warned[device.name] = state_value


@contextmanager
def singleton_lock(path=LOCK_PATH):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
            raise CanFailure(7, "Unsafe instance lock ownership or permissions: " + str(path))
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise CanFailure(7, "Cannot acquire CAN instance lock (another instance or permission error): " + str(exc)) from exc
    except CanFailure:
        if descriptor is not None:
            os.close(descriptor)
        raise
    try:
        yield
    finally:
        os.close(descriptor)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("can_bus.json"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-config", action="store_true")
    modes.add_argument("--scan", action="store_true")
    modes.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(args)
    stop = threading.Event()
    previous_handlers = {}
    try:
        if options.scan:
            runner = IpRunner(find_ip(), 3.0)
            observations = read_observations(runner)
            print(json.dumps([vars(item) for item in observations.values() if item.kind == "can"], indent=2), flush=True)
            return 0
        config = load_config(options.config)
        if options.check_config:
            log("CONFIG", f"Validated {len(config.devices)} required CAN mappings")
            return 0
        if not options.dry_run and os.geteuid() != 0:
            raise CanFailure(7, "Activation requires root: use an administrator-approved fixed sudo -n command")
        runner = IpRunner(find_ip(), config.command_timeout)
        observe = lambda: read_observations(runner)
        if options.dry_run:
            matched = validate_required(config, observe())
            for device in config.devices:
                reason = unavailable_reason(device, matched[device.name])
                log("PLAN", describe(device, matched[device.name]) + ("; initialize: " + reason if reason else "; no writes needed"))
            return 0
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
        with singleton_lock():
            return Supervisor(config, observe, runner, stop).run()
    except CanFailure as exc:
        if stop.is_set():
            return 0
        log("FAIL", f"exit={exc.code}: {exc}\ninspect power/cabling/configuration, then restart can_health")
        return exc.code
    except Exception as exc:
        log("FAIL", "exit=6: unexpected observation/control error: " + repr(exc))
        return 6
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main())
