from realsense_manager_msgs.srv import SetCameraProfile


class CommonParameterServices:
    """Optional convenience services; register this class in ManagerCore to enable."""

    def __init__(self, core):
        self._core = core
        self._service = core.node.create_service(
            SetCameraProfile,
            '~/set_camera_profile',
            self._set_profile,
        )

    def destroy(self):
        self._core.node.destroy_service(self._service)

    def _set_profile(self, request, response):
        if not self._core.require_active(response):
            return response
        try:
            if not request.parameter_name.endswith('_profile'):
                raise ValueError('parameter_name must end with _profile')
            if request.width == 0 or request.height == 0 or request.fps == 0:
                raise ValueError('width, height, and fps must be greater than zero')
            profile = f'{request.width}x{request.height}x{request.fps}'
            revision = self._core.store.set_parameters(
                request.alias, {request.parameter_name: profile})
            response.success = True
            response.message = f'Set {request.parameter_name}={profile}; restart launch to apply'
            response.config_revision = revision
            response.restart_required = True
        except (RuntimeError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self._core.revision()
            response.restart_required = False
        self._core.publish_event(
            'set_camera_profile', request.alias, response.success,
            response.message, response.config_revision)
        return response
