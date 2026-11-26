import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from realsense_manager.package_info import installed_package_version


def launch_setup(context):
    package_share = get_package_share_directory('realsense_manager')
    settings_path = os.path.join(package_share, 'config', 'global_settings.yaml')
    with open(settings_path, 'r', encoding='utf-8') as stream:
        use_lifecycle = bool(yaml.safe_load(stream).get('use_lifecycle_node', False))

    action_type = LifecycleNode if use_lifecycle else Node
    executable = (
        'realsense_lifecycle_manager_node' if use_lifecycle
        else 'realsense_manager_node'
    )
    manager_version = installed_package_version('realsense_manager')
    msgs_version = installed_package_version('realsense_manager_msgs')
    return [
        LogInfo(msg=(
            f'Starting RealSense manager v{manager_version} '
            f'(realsense_manager_msgs v{msgs_version}, lifecycle={use_lifecycle})')),
        action_type(
            package='realsense_manager',
            executable=executable,
            name='realsense_manager',
            namespace='',
            output='screen',
            parameters=[{
                'config_file': os.path.expanduser(
                    LaunchConfiguration('config_file').perform(context)),
                'enumerate_timeout': LaunchConfiguration('enumerate_timeout'),
            }],
        ),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=os.path.expanduser('~/.config/realsense_manager/cameras.yaml'),
            description='Writable persistent camera configuration'),
        DeclareLaunchArgument(
            'enumerate_timeout', default_value='10.0',
            description='Timeout for rs-enumerate-devices'),
        OpaqueFunction(function=launch_setup),
    ])
