"""
resolver.py

Resolve camera alias to current /dev/videoX
"""

from __future__ import annotations

from typing import Dict, Optional

try:
    from .scanner import CameraScanner
    from .yaml_manager import CameraYamlManager
    from .models import CameraInfo
except ImportError:
    from scanner import CameraScanner
    from yaml_manager import CameraYamlManager
    from models import CameraInfo


class CameraResolver:
    """
    Resolve configured camera aliases to current video devices.
    """

    def __init__(self):

        self.scanner = CameraScanner()
        self.yaml = CameraYamlManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, alias: str) -> Optional[str]:
        """
        Resolve alias -> /dev/videoX

        Returns
        -------
        "/dev/video6"
        or
        None
        """

        mapping = self.resolve_all()

        return mapping.get(alias)

    # ------------------------------------------------------------------

    def resolve_info(self, alias: str) -> Optional[CameraInfo]:
        """
        Resolve alias -> CameraInfo
        """

        configs = self.yaml.load()

        if alias not in configs:
            return None

        usb_path = configs[alias].usb_path

        return self.scanner.find_by_usb_path(usb_path)

    def configured_usb_path(self, alias: str) -> Optional[str]:
        """Return the configured stable USB path for an alias."""
        config = self.yaml.load().get(alias)
        return config.usb_path if config is not None else None

    # ------------------------------------------------------------------

    def resolve_all(self) -> Dict[str, str]:
        """
        Resolve all aliases.

        Returns

        {
            "front": "/dev/video6",
            "left": "/dev/video8",
        }
        """

        result: Dict[str, str] = {}

        configs = self.yaml.load()

        for alias, config in configs.items():

            camera = self.scanner.find_by_usb_path(
                config.usb_path
            )

            if camera is None:
                continue

            result[alias] = camera.device

        return result

    # ------------------------------------------------------------------

    def check(self) -> bool:
        """
        Check all configured cameras exist.

        Returns
        -------
        True if all OK.
        """

        ok = True

        configs = self.yaml.load()

        for alias, config in configs.items():

            camera = self.scanner.find_by_usb_path(
                config.usb_path
            )

            if camera is None:

                print(
                    f"[ERROR] {alias:<15} "
                    f"{config.usb_path:<15} "
                    f"NOT FOUND"
                )

                ok = False

            else:

                print(
                    f"[ OK ] {alias:<15} "
                    f"{camera.device:<15}"
                    f"{camera.usb_path}"
                )

        return ok

    # ------------------------------------------------------------------

    def doctor(self):
        """
        Print diagnostic information.
        """

        configs = self.yaml.load()

        print()

        print("=" * 70)
        print("USB Camera Diagnostics")
        print("=" * 70)

        found = 0

        for alias, config in configs.items():

            camera = self.scanner.find_by_usb_path(
                config.usb_path
            )

            print()

            print(f"Alias      : {alias}")
            print(f"Configured : {config.usb_path}")

            if camera is None:

                print("Status     : NOT FOUND")

                continue

            found += 1

            print(f"Device     : {camera.device}")
            print(f"Product    : {camera.product}")
            print(f"USB Path   : {camera.usb_path}")
            print(f"Capture    : Yes")

        print()

        print("=" * 70)
        print(f"Configured : {len(configs)}")
        print(f"Found      : {found}")
        print(f"Missing    : {len(configs)-found}")
        print("=" * 70)
