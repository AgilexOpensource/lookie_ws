import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List


USB_PATH_PATTERN = re.compile(r'/([0-9]+-[0-9]+(?:\.[0-9]+)*)(?::[0-9.]+)?(?:/|$)')


def normalize_usb_path(physical_port: str) -> str:
    matches = USB_PATH_PATTERN.findall(physical_port)
    return matches[-1] if matches else physical_port.strip()


@dataclass(frozen=True)
class DeviceRecord:
    fields: Dict[str, str]

    @property
    def serial_number(self) -> str:
        return self.fields.get('Serial Number', '')

    @property
    def physical_port(self) -> str:
        return self.fields.get('Physical Port', '')

    @property
    def usb_path(self) -> str:
        return normalize_usb_path(self.physical_port)


class DeviceEnumerationError(RuntimeError):
    pass


class DeviceEnumerator:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def enumerate(self) -> List[DeviceRecord]:
        try:
            result = subprocess.run(
                ['rs-enumerate-devices', '-S'],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DeviceEnumerationError('rs-enumerate-devices is not installed') from exc
        except subprocess.TimeoutExpired as exc:
            raise DeviceEnumerationError('rs-enumerate-devices timed out') from exc

        if result.returncode != 0:
            detail = result.stderr.strip() or f'exit code {result.returncode}'
            raise DeviceEnumerationError(f'rs-enumerate-devices failed: {detail}')

        return self.parse_output(result.stdout)

    @staticmethod
    def parse_output(output: str) -> List[DeviceRecord]:
        records = []
        current = None
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line == 'Device info:':
                if current:
                    records.append(DeviceRecord(current))
                current = {}
                continue
            if current is None or ':' not in line:
                continue
            key, value = line.split(':', 1)
            current[key.strip()] = value.strip()
        if current:
            records.append(DeviceRecord(current))
        return records
