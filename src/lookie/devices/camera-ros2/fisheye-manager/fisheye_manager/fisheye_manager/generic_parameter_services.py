from rclpy.parameter import Parameter

from fisheye_manager_msgs.srv import SetCameraParameters


class GenericParameterServices:
    """Stores arbitrary typed ROS parameters for an alias."""

    def __init__(self, core):
        self._core = core
        self._service = core.node.create_service(
            SetCameraParameters,
            '~/set_camera_parameters',
            self._set_parameters,
        )

    def destroy(self):
        self._core.node.destroy_service(self._service)

    def _set_parameters(self, request, response):
        if not self._core.require_active(response):
            return response
        try:
            values = {}
            for parameter_msg in request.parameters:
                parameter = Parameter.from_parameter_msg(parameter_msg)
                if parameter.type_ == Parameter.Type.NOT_SET:
                    raise ValueError(f'Parameter {parameter.name} has no value')
                values[parameter.name] = parameter.value
            revision = self._core.store.set_parameters(request.alias, values)
            response.success = True
            response.message = (
                f'Updated {len(values)} parameter(s); restart launch to apply')
            response.config_revision = revision
            response.restart_required = True
        except (RuntimeError, TypeError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self._core.revision()
            response.restart_required = False
        self._core.publish_event(
            'set_camera_parameters', request.alias, response.success,
            response.message, response.config_revision)
        return response
