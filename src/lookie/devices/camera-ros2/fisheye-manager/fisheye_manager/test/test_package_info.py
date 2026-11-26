from pathlib import Path

import pytest

from fisheye_manager.package_info import read_package_version


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SRC = PACKAGE_ROOT.parent


def test_read_package_version_from_package_xml():
    manager_xml = PACKAGE_ROOT / 'package.xml'
    msgs_xml = WORKSPACE_SRC / 'fisheye_manager_msgs' / 'package.xml'
    manager_version = read_package_version(manager_xml)
    msgs_version = read_package_version(msgs_xml)

    assert manager_version
    assert manager_version == msgs_version


def test_read_package_version_rejects_missing_version(tmp_path):
    package_xml = tmp_path / 'package.xml'
    package_xml.write_text('<package format="3"><name>demo</name></package>\n')

    with pytest.raises(ValueError, match='Missing version'):
        read_package_version(package_xml)
