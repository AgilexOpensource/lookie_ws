"""
utils.py

Common utility functions.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


# ============================================================
# Command
# ============================================================

def run_command(cmd: Sequence[str]) -> str:
    """
    Execute command and return stdout.

    Raises:
        RuntimeError
    """

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    return result.stdout


# ============================================================
# Parse
# ============================================================

def parse_properties(text: str) -> Dict[str, str]:
    """
    Parse

    KEY=value

    to dict.
    """

    props = {}

    for line in text.splitlines():

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        props[key] = value

    return props


# ============================================================
# USB
# ============================================================

_USB_RE = re.compile(
    r"usb-\d+:([0-9\-\.]+:\d+\.\d+)"
)


def extract_usb_path(id_path: str) -> str | None:
    """
    Convert

    pci-0000:00:14.0-usb-0:3:1.0

    to

    1-3:1.0
    """

    m = _USB_RE.search(id_path)

    if not m:
        return None

    return "1-" + m.group(1)


# ============================================================
# YAML
# ============================================================

def get_default_yaml_path() -> Path:
    """
    Return

    package/config/cameras.yaml
    """

    return (
        Path(__file__).resolve().parent.parent
        / "config"
        / "cameras.yaml"
    )


# ============================================================
# Console
# ============================================================

def print_header(title: str, width: int = 80):

    print()

    print("=" * width)

    print(title)

    print("=" * width)


def print_success(msg: str):

    print(f"[ OK ] {msg}")


def print_warning(msg: str):

    print(f"[WARN] {msg}")


def print_error(msg: str):

    print(f"[ERROR] {msg}")


# ============================================================
# User
# ============================================================

def confirm(
    message: str,
    default: bool = False,
) -> bool:

    prompt = "[Y/n]" if default else "[y/N]"

    ans = input(
        f"{message} {prompt} "
    ).strip().lower()

    if ans == "":
        return default

    return ans in (
        "y",
        "yes",
    )


# ============================================================
# Table
# ============================================================

def print_table(
    headers: List[str],
    rows: Iterable[Sequence],
):

    widths = [
        len(h)
        for h in headers
    ]

    cache = []

    for row in rows:

        row = [str(i) for i in row]

        cache.append(row)

        for i, item in enumerate(row):

            widths[i] = max(
                widths[i],
                len(item),
            )

    fmt = "  ".join(
        f"{{:<{w}}}"
        for w in widths
    )

    print(
        fmt.format(*headers)
    )

    print(
        "-" * (
            sum(widths)
            + len(widths) * 2
        )
    )

    for row in cache:

        print(
            fmt.format(*row)
        )