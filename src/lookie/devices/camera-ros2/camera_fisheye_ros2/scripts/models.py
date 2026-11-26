"""
models.py

Data models for USB Camera Manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


# ============================================================
# Runtime Camera Information
# ============================================================

@dataclass(slots=True)
class CameraInfo:
    """
    Physical USB camera detected from the system.
    """

    # /dev/videoX
    device: str

    # e.g. 1-3:1.0
    usb_path: str

    # DECXIN CAMERA
    product: str = ""

    # SunplusIT
    vendor: str = ""

    # 1bcf
    vendor_id: str = ""

    # 2cd1
    product_id: str = ""

    # USB serial (may be empty)
    serial: str = ""

    # True if ID_V4L_CAPABILITIES contains capture
    capture: bool = True

    @property
    def vid_pid(self) -> str:
        return f"{self.vendor_id}:{self.product_id}"


# ============================================================
# YAML Configuration
# ============================================================

@dataclass(slots=True)
class CameraConfig:
    """
    Camera configuration stored in cameras.yaml
    """

    # camera alias
    alias: str

    # 1-3:1.0
    usb_path: str

    # Optional information
    product: str = ""

    vendor: str = ""

    vendor_id: str = ""

    product_id: str = ""

    serial: str = ""


# ============================================================
# Resolver Result
# ============================================================

@dataclass(slots=True)
class CameraMapping:
    """
    Alias -> Current Video Device
    """

    alias: str

    device: str

    usb_path: str

    info: Optional[CameraInfo] = None


# ============================================================
# Collection Aliases
# ============================================================

CameraInfoDict = Dict[str, CameraInfo]
CameraConfigDict = Dict[str, CameraConfig]
CameraMappingDict = Dict[str, CameraMapping]