import os

from fisheye_manager.package_info import installed_package_version
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def launch_setup(context):
    manager_version = installed_package_version('fisheye_manager')
    msgs_version = installed_package_version('fisheye_manager_msgs')
    return [
        LogInfo(msg=(
            f'Starting Fisheye manager v{manager_version} '
            f'(fisheye_manager_msgs v{msgs_version})')),
        Node(
            package='fisheye_manager',
            executable='fisheye_manager_node',
            name='fisheye_manager',
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
            default_value=os.path.expanduser(
                '~/.config/fisheye_manager/cameras.yaml'),
            description='Writable persistent camera configuration'),
        DeclareLaunchArgument(
            'enumerate_timeout', default_value='10.0',
            description='Timeout for udevadm device queries'),
        OpaqueFunction(function=launch_setup),
    ])
