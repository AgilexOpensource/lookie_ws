import yaml
import pytest

from fisheye_manager.config_store import ConfigError, ConfigStore


def test_alias_binding_and_parameters(tmp_path):
    store = ConfigStore(str(tmp_path / 'cameras.yaml'))

    assert store.create_alias('front', 'camera_front', '') == 1
    assert store.set_expected_usb_path('front', '1-10.1:1.0') == 2
    assert store.set_parameters(
        'front', {'camera_fps': 30, 'camera_width': 640}) == 3

    camera = store.snapshot()['cameras']['front']
    assert store.snapshot()['schema_version'] == 1
    assert camera['expected_usb_path'] == '1-10.1:1.0'
    assert camera['parameters']['camera_fps'] == 30
    assert camera['parameters']['camera_name'] == 'camera_front'


def test_usb_path_may_only_have_one_alias(tmp_path):
    store = ConfigStore(str(tmp_path / 'cameras.yaml'))
    store.create_alias('left', 'camera_left', '')
    store.create_alias('right', 'camera_right', '')
    store.bind_camera('left', '1-10.1:1.0')

    with pytest.raises(ConfigError, match='already assigned'):
        store.bind_camera('right', '1-10.1:1.0')


def test_unsupported_schema_version_is_rejected(tmp_path):
    config_path = tmp_path / 'cameras.yaml'
    config_path.write_text(yaml.safe_dump({
        'schema_version': 2,
        'revision': 0,
        'cameras': {},
    }, sort_keys=False))

    with pytest.raises(ConfigError, match='Unsupported schema_version'):
        ConfigStore(str(config_path)).snapshot()


def test_camera_name_must_be_unique_for_create_and_update(tmp_path):
    store = ConfigStore(str(tmp_path / 'cameras.yaml'))
    store.create_alias('left', 'camera_left', '')

    with pytest.raises(ConfigError, match='already used by alias left'):
        store.create_alias('head', 'camera_left', '')

    store.create_alias('head', 'camera_head', '')
    with pytest.raises(ConfigError, match='already used by alias left'):
        store.update_alias('head', 'camera_left', '', True)
    with pytest.raises(ConfigError, match='already used by alias left'):
        store.set_parameters('head', {'camera_name': 'camera_left'})


def test_duplicate_camera_name_in_manual_yaml_is_rejected(tmp_path):
    config_path = tmp_path / 'cameras.yaml'
    config_path.write_text(yaml.safe_dump({
        'schema_version': 1,
        'revision': 0,
        'cameras': {
            'left': {'parameters': {'camera_name': 'camera_shared'}},
            'head': {'parameters': {'camera_name': 'camera_shared'}},
        },
    }, sort_keys=False))

    with pytest.raises(ConfigError, match='already used by alias left'):
        ConfigStore(str(config_path)).snapshot()
