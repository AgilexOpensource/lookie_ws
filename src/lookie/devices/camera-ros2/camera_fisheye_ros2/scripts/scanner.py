"""
USB Camera Scanner

Only responsible for:

1. Scan /dev/video*
2. Read udev information
3. Filter capture device
4. Return CameraInfo list
"""

from __future__ import annotations

import subprocess
from typing import Dict, List

try:
    from .models import CameraInfo
except ImportError:
    from models import CameraInfo

import glob
import re


class CameraScanner:

    FISHEYE_PRODUCT = "DECXIN  CAMERA: DECXIN  CAMERA"
    FISHEYE_VENDOR_ID = "1bcf"
    FISHEYE_PRODUCT_ID = "2cd1"

    def __init__(self):
        pass

    ######################################################################
    # Public
    ######################################################################

    def scan(self) -> List[CameraInfo]:
        """
        Scan all available capture cameras.

        Returns
        -------
        List[CameraInfo]
        """

        cameras: List[CameraInfo] = []

        for device in sorted(glob.glob("/dev/video*")):

            props = self._read_udev(device)

            if not props:
                continue

            camera = self._parse_camera(device, props)

            if camera is None:
                continue

            cameras.append(camera)

        return cameras

    def find_by_usb_path(self, usb_path: str) -> CameraInfo | None:
        """
        Find current camera device by stable USB path.
        """

        for camera in self.scan():

            if camera.usb_path == usb_path:

                return camera

        return None

    ######################################################################
    # Private
    ######################################################################

    def _read_udev(self, device: str) -> Dict[str, str]:
        """
        Read udev properties.
        """

        try:

            result = subprocess.run(
                [
                    "udevadm",
                    "info",
                    "-q",
                    "property",
                    "-n",
                    device,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        except Exception:

            return {}

        props: Dict[str, str] = {}

        for line in result.stdout.splitlines():

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            props[key] = value

        return props

    ######################################################################

    def _parse_camera(
        self,
        device: str,
        props: Dict[str, str],
    ) -> CameraInfo | None:
        """
        Parse one video node.
        """

        capability = props.get("ID_V4L_CAPABILITIES", "")

        if "capture" not in capability:
            return None

        product = props.get("ID_V4L_PRODUCT", "Unknown")
        vendor_id = props.get("ID_VENDOR_ID", "")
        product_id = props.get("ID_MODEL_ID", "")

        if not self._is_fisheye_camera(
            product,
            vendor_id,
            product_id,
        ):

            return None

        usb_path = self._parse_usb_path(
            props.get("ID_PATH", "")
        )

        if usb_path is None:
            return None

        return CameraInfo(

            device=device,

            usb_path=usb_path,

            product=product,

            vendor=props.get(
                "ID_VENDOR",
                "Unknown"
            ),

            vendor_id=vendor_id,

            product_id=product_id,

            serial=props.get(
                "ID_SERIAL_SHORT",
                props.get(
                    "ID_SERIAL",
                    ""
                ),
            ),

            capture=True,
        )

    ######################################################################

    @staticmethod
    def _is_fisheye_camera(
        product: str,
        vendor_id: str,
        product_id: str,
    ) -> bool:
        """
        This package is dedicated to the DECXIN fisheye camera.
        """

        return (
            product.strip() == CameraScanner.FISHEYE_PRODUCT
            and vendor_id.lower() == CameraScanner.FISHEYE_VENDOR_ID
            and product_id.lower() == CameraScanner.FISHEYE_PRODUCT_ID
        )

    ######################################################################

    @staticmethod
    def _parse_usb_path(path: str) -> str | None:
        """
        Convert

        pci-0000:00:14.0-usb-0:3:1.0

        to

        1-3:1.0
        """

        m = re.search(
            r"usb-\d+:([0-9\-\.]+:\d+\.\d+)",
            path,
        )

        if not m:
            return None

        return "1-" + m.group(1)

    ######################################################################

    @staticmethod
    def print_table(
        cameras: List[CameraInfo],
        aliases_by_usb_path: Dict[str, str] | None = None,
    ) -> None:

        aliases_by_usb_path = aliases_by_usb_path or {}

        headers = [
            "Video",
            "Alias",
            "USB Path",
            "Product",
            "VID:PID",
            "Serial",
        ]

        rows = [
            [
                cam.device,
                aliases_by_usb_path.get(cam.usb_path, "none"),
                cam.usb_path,
                cam.product,
                cam.vid_pid,
                cam.serial,
            ]
            for cam in cameras
        ]

        widths = [len(header) for header in headers]

        for row in rows:

            for index, value in enumerate(row):

                widths[index] = max(widths[index], len(value))

        line = "  ".join("=" * width for width in widths)
        fmt = "  ".join(f"{{:<{width}}}" for width in widths)

        print()
        print(line)
        print(fmt.format(*headers))
        print(line)

        for row in rows:

            print(fmt.format(*row))

        print(line)
