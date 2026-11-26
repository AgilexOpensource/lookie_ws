"""
yaml_manager.py

Read / Write cameras.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

try:
    from .models import CameraConfig, CameraInfo
except ImportError:
    from models import CameraConfig, CameraInfo


class CameraYamlManager:
    """
    Manage cameras.yaml
    """

    def __init__(self, yaml_path: str | Path | None = None):

        if yaml_path is None:

            root = Path(__file__).resolve().parent.parent

            if (root / "package.xml").exists():

                yaml_path = root / "config" / "cameras.yaml"

            else:

                try:
                    from ament_index_python.packages import get_package_share_directory

                    yaml_path = (
                        Path(get_package_share_directory("fisheye_ros2"))
                        / "config"
                        / "cameras.yaml"
                    )

                except Exception:

                    yaml_path = root / "config" / "cameras.yaml"

        self.yaml_path = Path(yaml_path)

    # ------------------------------------------------------------------
    # basic
    # ------------------------------------------------------------------

    def exists(self) -> bool:

        return self.yaml_path.exists()

    # ------------------------------------------------------------------

    def load(self) -> Dict[str, CameraConfig]:

        if not self.exists():

            return {}

        with open(self.yaml_path, "r", encoding="utf-8") as f:

            data = yaml.safe_load(f)

        if data is None:

            return {}

        configs: Dict[str, CameraConfig] = {}

        for alias, item in data.get("cameras", {}).items():

            configs[alias] = CameraConfig(

                alias=alias,

                usb_path=item["usb_path"],

                product=item.get("product", ""),

                vendor=item.get("vendor", ""),

                vendor_id=item.get("vendor_id", ""),

                product_id=item.get("product_id", ""),

                serial=item.get("serial", ""),

            )

        return configs

    # ------------------------------------------------------------------

    def save(self, configs: Dict[str, CameraConfig]) -> None:

        data = {

            "cameras": {}

        }

        for alias, cfg in configs.items():

            data["cameras"][alias] = {

                "usb_path": cfg.usb_path,

                "product": cfg.product,

            }

            if cfg.vendor:
                data["cameras"][alias]["vendor"] = cfg.vendor

            if cfg.vendor_id:
                data["cameras"][alias]["vendor_id"] = cfg.vendor_id

            if cfg.product_id:
                data["cameras"][alias]["product_id"] = cfg.product_id

            if cfg.serial:
                data["cameras"][alias]["serial"] = cfg.serial

        self.yaml_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            self.yaml_path,
            "w",
            encoding="utf-8",
        ) as f:

            yaml.safe_dump(

                data,

                f,

                sort_keys=False,

                allow_unicode=True,

            )

    # ------------------------------------------------------------------
    # interactive
    # ------------------------------------------------------------------

    def interactive_create(
        self,
        cameras: List[CameraInfo],
        append: bool = False,
    ) -> None:

        configs: Dict[str, CameraConfig] = self.load() if append else {}
        existing_usb_paths = {
            config.usb_path
            for config in configs.values()
        }
        added = 0

        print()

        print("=" * 60)

        print("Camera Configuration")

        print("=" * 60)

        print()

        for cam in cameras:

            if append and cam.usb_path in existing_usb_paths:

                continue

            print()

            print(f"Video     : {cam.device}")

            print(f"USB Path  : {cam.usb_path}")

            print(f"Product   : {cam.product}")

            print()

            alias = input(
                "Alias (empty to skip): "
            ).strip()

            if alias == "":

                continue

            if alias in configs:

                print(f"Alias '{alias}' already exists, skipped.")

                continue

            configs[alias] = CameraConfig(

                alias=alias,

                usb_path=cam.usb_path,

                product=cam.product,

                vendor=cam.vendor,

                vendor_id=cam.vendor_id,

                product_id=cam.product_id,

                serial=cam.serial,

            )

            added += 1

        if append and added == 0:

            print()

            print("No new camera to add.")

            return

        self.save(configs)

        print()

        print(f"Saved -> {self.yaml_path}")

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(
        self,
        cameras: List[CameraInfo],
    ) -> None:
        """
        Update usb_path of configured cameras.

        Matching priority

        1. serial
        2. product
        """

        configs = self.load()

        if not configs:

            print("No configuration.")

            return

        changed = False

        for alias, cfg in configs.items():

            #
            # already exists
            #
            for cam in cameras:

                if cam.usb_path == cfg.usb_path:

                    break

            else:

                #
                # try find same camera
                #
                candidate = None

                for cam in cameras:

                    #
                    # serial first
                    #
                    if cam.serial and cam.serial == cfg.serial:

                        candidate = cam

                        break

                #
                # fallback
                #
                if candidate is None:

                    same = [

                        c for c in cameras

                        if c.product == cfg.product

                    ]

                    if len(same) == 1:

                        candidate = same[0]

                if candidate is None:

                    print(f"[MISS] {alias}")

                    continue

                print()

                print(f"{alias}")

                print(f"Old : {cfg.usb_path}")

                print(f"New : {candidate.usb_path}")

                ans = input("Update? [y/N] ")

                if ans.lower() == "y":

                    cfg.usb_path = candidate.usb_path

                    changed = True

        if changed:

            self.save(configs)

            print()

            print("Configuration updated.")

        else:

            print()

            print("Nothing changed.")
