"""Launch hipnuc IMU node."""
import os
import yaml
from launch import LaunchDescription
import launch_ros.actions
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue

configurable_parameters = [
    {'name': 'serial_port',             'default': '/dev/head_imu',               'description': 'IMU serial port'},
    {'name': 'baud_rate',               'default': '460800',                      'description': 'serial baud rate'},
    {'name': 'frame_id',                'default': 'imu_head',                    'description': 'IMU frame id'},
    {'name': 'imu_switch',              'default': 'true',                        'description': 'enable IMU topic'},
    {'name': 'imu_topic',               'default': '/imu_head_data',              'description': 'IMU topic name'},
    {'name': 'euler_switch',            'default': 'true',                        'description': 'enable euler topic'},
    {'name': 'euler_topic',             'default': '/imu_head_euler_data',        'description': 'euler topic name'},
    {'name': 'magnetic_switch',         'default': 'false',                       'description': 'enable magnetic topic'},
    {'name': 'magnetic_topic',          'default': '/imu_head_magnetic_data',     'description': 'magnetic topic name'},
    {'name': 'temperature_switch',      'default': 'false',                       'description': 'enable temperature topic'},
    {'name': 'temperature_topic',       'default': '/imu_head_temp_data',         'description': 'temperature topic name'},
    {'name': 'pressure_switch',         'default': 'false',                       'description': 'enable pressure topic'},
    {'name': 'pressure_topic',          'default': '/imu_head_pressure_data',     'description': 'pressure topic name'},
    {'name': 'config_file',             'default': "''",                          'description': 'YAML config file path; absolute path recommended, relative path resolved from the launch working directory'},
    {'name': 'log_level',               'default': 'info',                        'description': 'debug log level [DEBUG|INFO|WARN|ERROR|FATAL]'},
    {'name': 'output',                  'default': 'screen',                      'description': 'pipe node output [screen|log]'},
    {'name': 'publish_tf',              'default': 'true',                        'description': 'publish IMU orientation TF'},
    {'name': 'tf_parent_frame',         'default': 'world',                       'description': 'parent frame for IMU orientation TF'},
    {'name': 'tf_child_frame_id',       'default': '',                            'description': 'TF child frame (empty uses frame_id)'},
    {'name': 'wait_for_device_timeout', 'default': '-1.0',                        'description': 'Initial wait for valid IMU data in seconds; -1 waits forever'},
    {'name': 'reconnect_timeout',       'default': '6.0',                         'description': 'Delay in seconds before each reconnection attempt'},
    {'name': 'reconnect_attempts',      'default': '-1',                          'description': 'Retries per disconnect: -1 unlimited, 0 exit immediately'},
    {'name': 'data_timeout',            'default': '2.0',                         'description': 'Seconds without valid IMU data before disconnect'},
    {'name': 'imu_install_roll_deg',    'default': '0.0',                         'description': 'Right-hand attitude calibration roll in degrees (sensor-local axes)'},
    {'name': 'imu_install_pitch_deg',   'default': '0.0',                         'description': 'Right-hand attitude calibration pitch in degrees (sensor-local axes)'},
    {'name': 'imu_install_yaw_deg',     'default': '0.0',                         'description': 'Right-hand attitude calibration yaw in degrees (sensor-local axes)'},
    {'name': 'installation',            'default': '0,0,-1,-1,0,0,0,1,0',         'description': 'Device URFR matrix or code; empty leaves device unchanged'},
    {'name': 'command_timeout_ms',      'default': '2000',                        'description': 'Serial command timeout in milliseconds'},
    {'name': 'calibration_save',        'default': 'false',                       'description': 'Save level calibration to device Flash'},
    {'name': 'command_verification',    'default': 'true',                        'description': 'Verify device command replies and installation readback'},
    {'name': 'session_valid_topic',     'default': '/imu_head_session_valid',     'description': 'Current connection session validity (std_msgs/Bool)'},
    {'name': 'yaw_reset_applied_topic', 'default': '/imu_head_yaw_reset_applied', 'description': 'Acknowledged yaw reset in current session (std_msgs/Bool)'},
]

_LAUNCH_ONLY_PARAMS = {'config_file', 'log_level', 'output'}


def declare_configurable_parameters(parameters):
    return [DeclareLaunchArgument(param['name'], default_value=param['default'], description=param['description']) for param in parameters]


def set_configurable_parameters(parameters):
    return dict([(param['name'], LaunchConfiguration(param['name'])) for param in parameters])


def yaml_to_dict(path_to_yaml):
    with open(path_to_yaml, 'r') as f:
        data = yaml.load(f, Loader=yaml.SafeLoader) or {}
    if not isinstance(data, dict):
        return data
    if 'IMU_publisher' in data and isinstance(data['IMU_publisher'], dict):
        node_cfg = data['IMU_publisher']
        return node_cfg.get('ros__parameters', node_cfg)
    return data.get('ros__parameters', data)


def launch_setup(context, params, param_name_suffix=''):
    _config_file = LaunchConfiguration('config_file' + param_name_suffix).perform(context)
    params_from_file = {} if _config_file == "''" else yaml_to_dict(_config_file)
    node_params = {name: value for name, value in params.items() if name not in _LAUNCH_ONLY_PARAMS}

    for name in ('wait_for_device_timeout', 'reconnect_timeout', 'data_timeout',
                 'imu_install_roll_deg', 'imu_install_pitch_deg', 'imu_install_yaw_deg'):
        node_params[name] = ParameterValue(params[name], value_type=float)
    node_params['reconnect_attempts'] = ParameterValue(params['reconnect_attempts'], value_type=int)
    node_params['command_timeout_ms'] = ParameterValue(params['command_timeout_ms'], value_type=int)
    node_params['calibration_save'] = ParameterValue(params['calibration_save'], value_type=bool)
    node_params['command_verification'] = ParameterValue(params['command_verification'], value_type=bool)
    node_params['tf_child_frame_id'] = ParameterValue(params['tf_child_frame_id'], value_type=str)
    node_params['installation'] = ParameterValue(params['installation'], value_type=str)
    node_params['session_valid_topic'] = ParameterValue(params['session_valid_topic'], value_type=str)
    node_params['yaw_reset_applied_topic'] = ParameterValue(params['yaw_reset_applied_topic'], value_type=str)

    _output = LaunchConfiguration('output' + param_name_suffix)
    if os.getenv('ROS_DISTRO') == 'foxy':
        _output = context.perform_substitution(_output)

    return [
        launch_ros.actions.Node(
            package='hipnuc_imu',
            executable='talker',
            name='IMU_publisher',
            parameters=[node_params, params_from_file],
            output=_output,
            arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level' + param_name_suffix)],
            emulate_tty=True,
        )
    ]


def generate_launch_description():
    return LaunchDescription(declare_configurable_parameters(configurable_parameters) + [
        OpaqueFunction(function=launch_setup, kwargs={'params': set_configurable_parameters(configurable_parameters)})
    ])
