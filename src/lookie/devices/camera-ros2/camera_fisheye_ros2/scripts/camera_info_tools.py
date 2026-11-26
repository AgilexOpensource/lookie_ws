#!/usr/bin/env python3
"""
Camera information query helpers.

Two input styles are supported:

1. USB path -> video, product, vid:pid, serial
2. /dev/video* -> usb path, product, vid:pid, serial
"""

from __future__ import annotations

try:
    from .models import CameraInfo
    from .scanner import CameraScanner
except ImportError:
    from models import CameraInfo
    from scanner import CameraScanner


class UsbPathCameraInfo:
    """
    Query current capture camera information by stable USB path.
    """

    def __init__(self, usb_path: str):
        self.usb_path = usb_path
        self.scanner = CameraScanner()
        self._camera: CameraInfo | None = None
        self._scanned = False

    def _get_camera(self) -> CameraInfo | None:
        if not self._scanned:
            self._camera = self.scanner.find_by_usb_path(self.usb_path)
            self._scanned = True

        return self._camera

    def get_video(self) -> str | None:
        camera = self._get_camera()
        return camera.device if camera else None

    def get_product(self) -> str | None:
        camera = self._get_camera()
        return camera.product if camera else None

    def get_vid_pid(self) -> str | None:
        camera = self._get_camera()
        return camera.vid_pid if camera else None

    def get_serial(self) -> str | None:
        camera = self._get_camera()
        return camera.serial if camera else None


class VideoCameraInfo:
    """
    Query current capture camera information by /dev/video* device.
    """

    def __init__(self, video: str | int):
        self.video = self._normalize_video(video)
        self.scanner = CameraScanner()
        self._camera: CameraInfo | None = None
        self._scanned = False

    @staticmethod
    def _normalize_video(video: str | int) -> str:
        value = str(video).strip()

        if value.isdigit():
            return f"/dev/video{value}"

        if value.startswith("video"):
            return f"/dev/{value}"

        return value

    def _get_camera(self) -> CameraInfo | None:
        if not self._scanned:
            self._camera = next(
                (
                    camera
                    for camera in self.scanner.scan()
                    if camera.device == self.video
                ),
                None,
            )
            self._scanned = True
        
        return self._camera

    def get_usb_path(self) -> str | None:
        camera = self._get_camera()
        return camera.usb_path if camera else None

    def get_product(self) -> str | None:
        camera = self._get_camera()
        return camera.product if camera else None

    def get_vid_pid(self) -> str | None:
        camera = self._get_camera()
        return camera.vid_pid if camera else None

    def get_serial(self) -> str | None:
        camera = self._get_camera()
        return camera.serial if camera else None
