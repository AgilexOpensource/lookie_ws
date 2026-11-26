import uuid
from pathlib import Path
from typing import Dict, List, Optional

from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from realsense_manager_msgs.msg import (
    AliasCamera,
    AliasInventory,
    AliasStatus,
    Device,
    DeviceInventory,
    ManagerEvent,
)
from realsense_manager_msgs.srv import (
    BindByUsb,
    BindCamera,
    CreateAlias,
    DeleteAlias,
    QueryAliases,
    QueryDevices,
    RenameAlias,
    SetExpectedUsbPath,
    UnbindCamera,
    UpdateAlias,
)

from .config_store import ConfigError, ConfigStore
from .device_enumerator import (
    DeviceEnumerationError,
    DeviceEnumerator,
    DeviceRecord,
    normalize_usb_path,
)
from .generic_parameter_services import GenericParameterServices
from .package_info import installed_package_version


DEFAULT_CONFIG_PATH = '~/.config/realsense_manager/cameras.yaml'


class ManagerCore:
    def __init__(self, node):
        self.node = node
        self.store: Optional[ConfigStore] = None
        self._enumerator: Optional[DeviceEnumerator] = None
        self._active = False
        self._configured = False
        self._devices: List[DeviceRecord] = []
        self._publishers = []
        self._services = []
        self._parameter_service_groups = []

    def configure(self) -> None:
        if self._configured:
            return
        if not self.node.has_parameter('config_file'):
            self.node.declare_parameter('config_file', DEFAULT_CONFIG_PATH)
        if not self.node.has_parameter('enumerate_timeout'):
            self.node.declare_parameter('enumerate_timeout', 10.0)

        config_path = self.node.get_parameter('config_file').value
        timeout = float(self.node.get_parameter('enumerate_timeout').value)
        self.store = ConfigStore(str(Path(config_path).expanduser()))
        self._enumerator = DeviceEnumerator(timeout)

        snapshot_qos = QoSProfile(depth=1)
        snapshot_qos.reliability = ReliabilityPolicy.RELIABLE
        snapshot_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.device_publisher = self.node.create_publisher(
            DeviceInventory, '~/device_inventory', snapshot_qos)
        self.alias_publisher = self.node.create_publisher(
            AliasInventory, '~/alias_inventory', snapshot_qos)
        self.event_publisher = self.node.create_publisher(
            ManagerEvent, '~/events', QoSProfile(depth=20))
        self._publishers.extend([
            self.device_publisher, self.alias_publisher, self.event_publisher])

        self._create_service(QueryDevices, '~/query_devices', self._query_devices)
        self._create_service(QueryAliases, '~/query_aliases', self._query_aliases)
        self._create_service(CreateAlias, '~/create_alias', self._create_alias)
        self._create_service(DeleteAlias, '~/delete_alias', self._delete_alias)
        self._create_service(RenameAlias, '~/rename_alias', self._rename_alias)
        self._create_service(UpdateAlias, '~/update_alias', self._update_alias)
        self._create_service(BindCamera, '~/bind_camera', self._bind_camera)
        self._create_service(BindByUsb, '~/bind_by_usb', self._bind_by_usb)
        self._create_service(UnbindCamera, '~/unbind_camera', self._unbind_camera)
        self._create_service(
            SetExpectedUsbPath, '~/set_expected_usb_path', self._set_expected_usb_path)

        # Optional custom parameter service groups are registered here when enabled.
        self._parameter_service_groups = [
            GenericParameterServices(self),
        ]
        self._configured = True
        manager_version = installed_package_version('realsense_manager')
        msgs_version = installed_package_version('realsense_manager_msgs')
        self.node.get_logger().info(
            f'RealSense Manager v{manager_version} '
            f'(realsense_manager_msgs v{msgs_version})')
        self.node.get_logger().info(f'Using camera configuration: {self.store.path}')

    def cleanup(self) -> None:
        if not self._configured:
            return
        self._active = False
        for group in self._parameter_service_groups:
            group.destroy()
        self._parameter_service_groups.clear()
        for service in self._services:
            self.node.destroy_service(service)
        self._services.clear()
        for publisher in self._publishers:
            self.node.destroy_publisher(publisher)
        self._publishers.clear()
        self.store = None
        self._enumerator = None
        self._devices = []
        self._configured = False

    def set_active(self, active: bool) -> None:
        self._active = active

    def _create_service(self, service_type, name, callback) -> None:
        self._services.append(self.node.create_service(service_type, name, callback))

    def require_active(self, response) -> bool:
        if self._active:
            return True
        response.success = False
        response.message = 'Manager is not active'
        if hasattr(response, 'config_revision'):
            response.config_revision = self.revision()
        if hasattr(response, 'restart_required'):
            response.restart_required = False
        return False

    def revision(self) -> int:
        if self.store is None:
            return 0
        try:
            return int(self.store.snapshot().get('revision', 0))
        except ConfigError:
            return 0

    def publish_event(
        self, operation: str, alias: str, success: bool, message: str, revision: int
    ) -> None:
        if not self._configured:
            return
        event = ManagerEvent()
        event.header.stamp = self.node.get_clock().now().to_msg()
        event.operation = operation
        event.alias = alias
        event.success = success
        event.message = message
        event.config_revision = revision
        self.event_publisher.publish(event)

    @staticmethod
    def _request_id(request_id: str) -> str:
        return request_id.strip() or str(uuid.uuid4())

    def _enumerate(self) -> List[DeviceRecord]:
        self._devices = self._enumerator.enumerate()
        return self._devices

    def _serial_bindings(self, config: Dict) -> Dict[str, str]:
        return {
            str(camera['parameters'].get('serial_no')): alias
            for alias, camera in config['cameras'].items()
            if camera['parameters'].get('serial_no')
        }

    def _device_message(self, record: DeviceRecord, bindings: Dict[str, str]) -> Device:
        fields = record.fields
        message = Device()
        message.info.name = fields.get('Name', '')
        message.info.serial_number = record.serial_number
        message.info.firmware_version = fields.get('Firmware Version', '')
        message.info.recommended_firmware_version = fields.get(
            'Recommended Firmware Version', '')
        message.info.physical_port = record.physical_port
        message.info.usb_path = record.usb_path
        message.info.debug_op_code = fields.get('Debug Op Code', '')
        message.info.advanced_mode = fields.get('Advanced Mode', '').upper() == 'YES'
        message.info.product_id = fields.get('Product Id', '')
        message.info.camera_locked = fields.get('Camera Locked', '').upper() == 'YES'
        message.info.usb_type_descriptor = fields.get('Usb Type Descriptor', '')
        message.info.product_line = fields.get('Product Line', '')
        message.info.asic_serial_number = fields.get('Asic Serial Number', '')
        message.info.firmware_update_id = fields.get('Firmware Update Id', '')
        message.info.dfu_device_path = fields.get('Dfu Device Path', '')
        message.info.connection_type = fields.get('Connection Type', '')
        message.status.alias = bindings.get(record.serial_number, '')
        message.status.is_binded = bool(message.status.alias)
        return message

    def _alias_message(self, alias: str, camera: Dict) -> AliasCamera:
        message = AliasCamera()
        parameters = camera.get('parameters', {})
        serial = str(parameters.get('serial_no') or '')
        expected_usb = str(camera.get('expected_usb_path') or '')
        current = next((item for item in self._devices if item.serial_number == serial), None)
        message.config.alias = alias
        message.config.enabled = bool(camera.get('enabled', True))
        message.config.expected_usb_path = expected_usb
        message.status.is_binded = bool(serial)
        message.status.device_present = current is not None
        message.status.current_usb_path = current.usb_path if current else ''
        message.status.usb_path_matches = bool(
            current and expected_usb and current.usb_path == expected_usb)
        message.status.runtime_state = AliasStatus.RUNTIME_UNKNOWN
        for name, value in sorted(camera.get('parameters', {}).items()):
            try:
                message.config.parameters.append(
                    Parameter(name, value=value).to_parameter_msg())
            except (TypeError, ValueError) as exc:
                self.node.get_logger().warning(f'Skipping invalid parameter {alias}.{name}: {exc}')
        return message

    def _publish_device_inventory(self, request_id: str, config: Dict) -> int:
        inventory = DeviceInventory()
        inventory.header.stamp = self.node.get_clock().now().to_msg()
        inventory.request_id = request_id
        bindings = self._serial_bindings(config)
        inventory.devices = [self._device_message(item, bindings) for item in self._devices]
        self.device_publisher.publish(inventory)
        return len(inventory.devices)

    def _publish_alias_inventory(self, request_id: str, alias_filter: str = '') -> int:
        config = self.store.snapshot()
        inventory = AliasInventory()
        inventory.header.stamp = self.node.get_clock().now().to_msg()
        inventory.request_id = request_id
        inventory.config_revision = int(config.get('revision', 0))
        for alias, camera in config['cameras'].items():
            if alias_filter and alias != alias_filter:
                continue
            inventory.cameras.append(self._alias_message(alias, camera))
        self.alias_publisher.publish(inventory)
        return len(inventory.cameras)

    def _query_devices(self, request, response):
        if not self.require_active(response):
            return response
        response.request_id = self._request_id(request.request_id)
        try:
            devices = self._enumerate()
            response.device_count = self._publish_device_inventory(
                response.request_id, self.store.snapshot())
            response.success = True
            response.message = f'Found {len(devices)} RealSense device(s)'
        except (ConfigError, DeviceEnumerationError) as exc:
            response.success = False
            response.message = str(exc)
        return response

    def _query_aliases(self, request, response):
        if not self.require_active(response):
            return response
        response.request_id = self._request_id(request.request_id)
        try:
            response.alias_count = self._publish_alias_inventory(
                response.request_id, request.alias.strip())
            response.config_revision = self.revision()
            if request.alias and response.alias_count == 0:
                raise ConfigError(f'Alias does not exist: {request.alias}')
            response.success = True
            response.message = f'Published {response.alias_count} alias record(s)'
        except ConfigError as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self.revision()
        return response

    def _run_mutation(self, operation, alias: str, callback, response):
        if not self.require_active(response):
            return response
        try:
            response.config_revision = callback()
            response.success = True
            response.message = f'{operation} succeeded; restart multi-camera launch to apply'
        except (ConfigError, DeviceEnumerationError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self.revision()
        self.publish_event(
            operation, alias, response.success, response.message,
            response.config_revision)
        return response

    def _create_alias(self, request, response):
        return self._run_mutation(
            'create_alias', request.alias,
            lambda: self.store.create_alias(
                request.alias, request.camera_name, request.camera_namespace), response)

    def _delete_alias(self, request, response):
        return self._run_mutation(
            'delete_alias', request.alias,
            lambda: self.store.delete_alias(request.alias), response)

    def _rename_alias(self, request, response):
        return self._run_mutation(
            'rename_alias', request.alias,
            lambda: self.store.rename_alias(request.alias, request.new_alias), response)

    def _update_alias(self, request, response):
        return self._run_mutation(
            'update_alias', request.alias,
            lambda: self.store.update_alias(
                request.alias, request.camera_name, request.camera_namespace,
                request.enabled), response)

    def _bind_camera(self, request, response):
        def bind():
            if request.require_present:
                serials = {device.serial_number for device in self._enumerate()}
                if request.serial_number not in serials:
                    raise ConfigError(f'Device is not connected: {request.serial_number}')
            return self.store.bind_camera(request.alias, request.serial_number)

        return self._run_mutation('bind_camera', request.alias, bind, response)

    def _unbind_camera(self, request, response):
        return self._run_mutation(
            'unbind_camera', request.alias,
            lambda: self.store.unbind_camera(request.alias), response)

    def _set_expected_usb_path(self, request, response):
        normalized = normalize_usb_path(request.usb_path)
        return self._run_mutation(
            'set_expected_usb_path', request.alias,
            lambda: self.store.set_expected_usb_path(request.alias, normalized), response)

    def _bind_by_usb(self, request, response):
        if not self.require_active(response):
            return response
        try:
            devices = self._enumerate()
            usb_to_serial = {device.usb_path: device.serial_number for device in devices}
            revision, bound, skipped, reasons = self.store.bind_by_usb(
                usb_to_serial, request.overwrite_existing)
            response.success = bound > 0 or skipped == 0
            response.bound_count = bound
            response.skipped_count = skipped
            response.config_revision = revision
            response.message = f'Bound {bound}, skipped {skipped}'
            if reasons:
                response.message += ': ' + '; '.join(reasons)
        except (ConfigError, DeviceEnumerationError) as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self.revision()
        self.publish_event(
            'bind_by_usb', '', response.success, response.message, response.config_revision)
        return response
