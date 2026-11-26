import copy
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Tuple

import yaml


ALIAS_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
CAMERA_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
CURRENT_SCHEMA_VERSION = 1


class ConfigError(RuntimeError):
    pass


class ConfigStore:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._ensure_file()

    @staticmethod
    def empty_config() -> Dict[str, Any]:
        return {
            'schema_version': CURRENT_SCHEMA_VERSION,
            'revision': 0,
            'cameras': {},
        }

    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_unlocked(self.empty_config())

    def _read_unlocked(self) -> Dict[str, Any]:
        try:
            with self.path.open('r', encoding='utf-8') as stream:
                data = yaml.safe_load(stream) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f'Cannot read configuration: {exc}') from exc

        if not isinstance(data, dict):
            raise ConfigError('Configuration root must be a mapping')
        schema_version = data.get('schema_version', CURRENT_SCHEMA_VERSION)
        if schema_version != CURRENT_SCHEMA_VERSION:
            raise ConfigError('Unsupported schema_version')
        cameras = data.setdefault('cameras', {})
        if not isinstance(cameras, dict):
            raise ConfigError('cameras must be a mapping')
        for alias, camera in cameras.items():
            if not isinstance(camera, dict):
                raise ConfigError(f'Camera configuration must be a mapping: {alias}')
            parameters = camera.setdefault('parameters', {})
            if not isinstance(parameters, dict):
                raise ConfigError(f'Camera parameters must be a mapping: {alias}')
            parameters.setdefault('serial_no', None)
            parameters.setdefault('camera_name', f'camera_{alias}')
            parameters.setdefault('camera_namespace', '')
        self._validate_unique_camera_names(data)
        data.setdefault('revision', 0)
        data['schema_version'] = CURRENT_SCHEMA_VERSION
        return data

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.path.parent,
                prefix=f'.{self.path.name}.', suffix='.tmp', delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ConfigError(f'Cannot write configuration: {exc}') from exc

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._read_unlocked())

    def _mutate(self, operation: Callable[[Dict[str, Any]], None]) -> int:
        with self._lock:
            data = self._read_unlocked()
            operation(data)
            data['revision'] = int(data.get('revision', 0)) + 1
            self._write_unlocked(data)
            return data['revision']

    @staticmethod
    def _validate_alias(alias: str) -> str:
        alias = alias.strip()
        if not ALIAS_PATTERN.fullmatch(alias):
            raise ConfigError(
                'Alias must start with a letter and contain only letters, digits, or underscores')
        return alias

    @staticmethod
    def _camera(data: Dict[str, Any], alias: str) -> Dict[str, Any]:
        try:
            return data['cameras'][alias]
        except KeyError as exc:
            raise ConfigError(f'Alias does not exist: {alias}') from exc

    @staticmethod
    def _validate_camera_name(camera_name: Any) -> str:
        if not isinstance(camera_name, str):
            raise ConfigError('camera_name must be a string')
        camera_name = camera_name.strip()
        if not CAMERA_NAME_PATTERN.fullmatch(camera_name):
            raise ConfigError(
                'camera_name must contain only letters, digits, or underscores '
                'and cannot start with a digit')
        return camera_name

    @classmethod
    def _validate_unique_camera_names(cls, data: Dict[str, Any]) -> None:
        owners = {}
        for alias, camera in data['cameras'].items():
            camera_name = cls._validate_camera_name(
                camera['parameters'].get('camera_name'))
            owner = owners.get(camera_name)
            if owner is not None:
                raise ConfigError(
                    f'camera_name {camera_name} is already used by alias {owner}')
            owners[camera_name] = alias

    @classmethod
    def _ensure_camera_name_available(
        cls, data: Dict[str, Any], alias: str, camera_name: Any
    ) -> str:
        camera_name = cls._validate_camera_name(camera_name)
        for other_alias, camera in data['cameras'].items():
            if other_alias != alias and (
                camera['parameters'].get('camera_name') == camera_name
            ):
                raise ConfigError(
                    f'camera_name {camera_name} is already used by alias '
                    f'{other_alias}')
        return camera_name

    def create_alias(self, alias: str, camera_name: str, camera_namespace: str) -> int:
        alias = self._validate_alias(alias)
        camera_name = camera_name.strip() or f'camera_{alias}'

        def operation(data):
            if alias in data['cameras']:
                raise ConfigError(f'Alias already exists: {alias}')
            validated_name = self._ensure_camera_name_available(
                data, alias, camera_name)
            data['cameras'][alias] = {
                'enabled': True,
                'expected_usb_path': None,
                'parameters': {
                    'serial_no': None,
                    'camera_name': validated_name,
                    'camera_namespace': camera_namespace.strip(),
                },
            }

        return self._mutate(operation)

    def delete_alias(self, alias: str) -> int:
        def operation(data):
            self._camera(data, alias)
            del data['cameras'][alias]

        return self._mutate(operation)

    def rename_alias(self, alias: str, new_alias: str) -> int:
        new_alias = self._validate_alias(new_alias)

        def operation(data):
            camera = self._camera(data, alias)
            if new_alias in data['cameras']:
                raise ConfigError(f'Alias already exists: {new_alias}')
            reordered = {}
            for name, value in data['cameras'].items():
                reordered[new_alias if name == alias else name] = camera if name == alias else value
            data['cameras'] = reordered

        return self._mutate(operation)

    def update_alias(
        self, alias: str, camera_name: str, camera_namespace: str, enabled: bool
    ) -> int:
        def operation(data):
            camera = self._camera(data, alias)
            camera['parameters']['camera_name'] = (
                self._ensure_camera_name_available(data, alias, camera_name))
            camera['parameters']['camera_namespace'] = camera_namespace.strip()
            camera['enabled'] = bool(enabled)

        return self._mutate(operation)

    def set_expected_usb_path(self, alias: str, usb_path: str) -> int:
        normalized = usb_path.strip() or None

        def operation(data):
            if normalized is not None:
                for name, camera in data['cameras'].items():
                    if name != alias and camera.get('expected_usb_path') == normalized:
                        raise ConfigError(f'USB path {normalized} is already assigned to {name}')
            self._camera(data, alias)['expected_usb_path'] = normalized

        return self._mutate(operation)

    def bind_camera(self, alias: str, serial_number: str) -> int:
        serial_number = serial_number.strip()
        if not serial_number:
            raise ConfigError('serial_number cannot be empty')

        def operation(data):
            for name, camera in data['cameras'].items():
                if name != alias and str(
                    camera['parameters'].get('serial_no') or ''
                ) == serial_number:
                    raise ConfigError(f'Serial number is already bound to {name}')
            self._camera(data, alias)['parameters']['serial_no'] = serial_number

        return self._mutate(operation)

    def unbind_camera(self, alias: str) -> int:
        def operation(data):
            self._camera(data, alias)['parameters']['serial_no'] = None

        return self._mutate(operation)

    def bind_by_usb(
        self, usb_to_serial: Dict[str, str], overwrite_existing: bool
    ) -> Tuple[int, int, int, Iterable[str]]:
        bound = 0
        skipped = 0
        reasons = []

        def operation(data):
            nonlocal bound, skipped
            planned_serials = {
                str(camera['parameters'].get('serial_no')): name
                for name, camera in data['cameras'].items()
                if camera['parameters'].get('serial_no')
            }
            for alias, camera in data['cameras'].items():
                usb_path = camera.get('expected_usb_path')
                if not usb_path:
                    skipped += 1
                    reasons.append(f'{alias}: expected_usb_path is not set')
                    continue
                serial = usb_to_serial.get(usb_path)
                if not serial:
                    skipped += 1
                    reasons.append(f'{alias}: no camera at {usb_path}')
                    continue
                if camera['parameters'].get('serial_no') and not overwrite_existing:
                    skipped += 1
                    reasons.append(f'{alias}: already bound')
                    continue
                owner = planned_serials.get(serial)
                if owner and owner != alias:
                    skipped += 1
                    reasons.append(f'{alias}: serial already bound to {owner}')
                    continue
                previous = str(camera['parameters'].get('serial_no') or '')
                if previous:
                    planned_serials.pop(previous, None)
                camera['parameters']['serial_no'] = serial
                planned_serials[serial] = alias
                bound += 1

        revision = self._mutate(operation)
        return revision, bound, skipped, reasons

    def set_parameters(self, alias: str, parameters: Dict[str, Any]) -> int:
        if not parameters:
            raise ConfigError('At least one parameter is required')
        if any(not name.strip() for name in parameters):
            raise ConfigError('Parameter names cannot be empty')

        def operation(data):
            camera = self._camera(data, alias)
            if 'camera_name' in parameters:
                parameters['camera_name'] = self._ensure_camera_name_available(
                    data, alias, parameters['camera_name'])
            camera.setdefault('parameters', {}).update(parameters)

        return self._mutate(operation)
