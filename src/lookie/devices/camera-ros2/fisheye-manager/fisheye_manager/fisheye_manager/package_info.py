from pathlib import Path
from xml.etree import ElementTree


def read_package_version(package_xml: Path) -> str:
    version = ElementTree.parse(package_xml).findtext('version')
    if not version or not version.strip():
        raise ValueError(f'Missing version in {package_xml}')
    return version.strip()


def installed_package_version(package_name: str) -> str:
    try:
        from ament_index_python.packages import get_package_share_directory
        return read_package_version(
            Path(get_package_share_directory(package_name)) / 'package.xml')
    except (LookupError, OSError, ElementTree.ParseError, ValueError):
        return 'unknown'
