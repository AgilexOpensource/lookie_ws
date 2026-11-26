import glob
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


FISHEYE_PRODUCT = 'DECXIN  CAMERA: DECXIN  CAMERA'
FISHEYE_VENDOR_ID = '1bcf'
FISHEYE_PRODUCT_ID = '2cd1'
ID_PATH_PATTERN = re.compile(r'usb-\d+:([0-9\-\.]+:\d+\.\d+)')
SHORT_USB_PATH_PATTERN = re.compile(r'^\d+-\d+(?:\.\d+)*(?::\d+\.\d+)?$')
VIDEO_INDEX_PATTERN = re.compile(r'^/dev/video(\d+)$')


class DeviceEnumerationError(RuntimeError):
    pass


def parse_id_path(id_path: str) -> Optional[str]:
    match = ID_PATH_PATTERN.search(id_path)
    if not match:
        return None
    return '1-' + match.group(1)


def normalize_usb_path(value: str) -> str:
    value = value.strip()
    if not value:
        return ''
    parsed = parse_id_path(value)
    if parsed:
        return parsed
    if SHORT_USB_PATH_PATTERN.fullmatch(value):
        return value
    return value


def video_index(device: str) -> int:
    match = VIDEO_INDEX_PATTERN.fullmatch(device)
    return int(match.group(1)) if match else 10**9


def _normalize_product(product: str) -> str:
    return ' '.join(product.split())


def is_fisheye_camera(product: str, vendor_id: str, product_id: str) -> bool:
    return (
        _normalize_product(product) == _normalize_product(FISHEYE_PRODUCT)
        and vendor_id.lower() == FISHEYE_VENDOR_ID
        and product_id.lower() == FISHEYE_PRODUCT_ID
    )


@dataclass(frozen=True)
class DeviceRecord:
    video_device: str
    usb_path: str
    product: str
    vendor: str
    vendor_id: str
    product_id: str
    serial: str
    capture: bool = True

    @property
    def vid_pid(self) -> str:
        return f'{self.vendor_id}:{self.product_id}'


class DeviceEnumerator:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def enumerate(self) -> List[DeviceRecord]:
        records = []
        try:
            devices = sorted(glob.glob('/dev/video*'), key=video_index)
        except OSError as exc:
            raise DeviceEnumerationError(f'Cannot scan video devices: {exc}') from exc

        for device in devices:
            props = self._read_udev(device)
            record = self.parse_properties(device, props)
            if record is not None:
                records.append(record)
        return records

    def _read_udev(self, device: str) -> Dict[str, str]:
        try:
            result = subprocess.run(
                ['udevadm', 'info', '-q', 'property', '-n', device],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DeviceEnumerationError('udevadm is not installed') from exc
        except subprocess.TimeoutExpired as exc:
            raise DeviceEnumerationError(f'udevadm timed out for {device}') from exc

        if result.returncode != 0:
            return {}
        return self.parse_udev_output(result.stdout)

    @staticmethod
    def parse_udev_output(output: str) -> Dict[str, str]:
        props: Dict[str, str] = {}
        for line in output.splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            props[key] = value
        return props

    @staticmethod
    def parse_properties(device: str, props: Dict[str, str]) -> Optional[DeviceRecord]:
        capability = props.get('ID_V4L_CAPABILITIES', '')
        if 'capture' not in capability:
            return None

        product = props.get('ID_V4L_PRODUCT', 'Unknown')
        vendor_id = props.get('ID_VENDOR_ID', '')
        product_id = props.get('ID_MODEL_ID', '')
        if not is_fisheye_camera(product, vendor_id, product_id):
            return None

        usb_path = parse_id_path(props.get('ID_PATH', ''))
        if usb_path is None:
            return None

        return DeviceRecord(
            video_device=device,
            usb_path=usb_path,
            product=product,
            vendor=props.get('ID_VENDOR', 'Unknown'),
            vendor_id=vendor_id,
            product_id=product_id,
            serial=props.get('ID_SERIAL_SHORT', props.get('ID_SERIAL', '')),
            capture=True,
        )
