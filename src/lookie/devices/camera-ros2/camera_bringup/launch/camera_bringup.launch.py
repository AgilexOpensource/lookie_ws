import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    fisheye_launch = os.path.join(
        get_package_share_directory('fisheye_manager'),
        'launch',
        'run_multi_camera.launch.py',
    )
    realsense_launch = os.path.join(
        get_package_share_directory('realsense_manager'),
        'launch',
        'run_multi_camera.launch.py',
    )

    launch_fisheye = LaunchConfiguration('launch_fisheye')
    launch_realsense = LaunchConfiguration('launch_realsense')
    log_level = LaunchConfiguration('log_level')

    return LaunchDescription([
        DeclareLaunchArgument(
            'launch_fisheye',
            default_value='true',
            description='Include fisheye_manager/run_multi_camera.launch.py',
        ),
        DeclareLaunchArgument(
            'launch_realsense',
            default_value='true',
            description='Include realsense_manager/run_multi_camera.launch.py',
        ),
        DeclareLaunchArgument(
            'fisheye_config_file',
            default_value=os.path.expanduser(
                '~/.config/fisheye_manager/cameras.yaml'),
            description='Fisheye manager camera configuration',
        ),
        DeclareLaunchArgument(
            'realsense_config_file',
            default_value=os.path.expanduser(
                '~/.config/realsense_manager/cameras.yaml'),
            description='RealSense manager camera configuration',
        ),
        DeclareLaunchArgument('log_level', default_value='info'),
        LogInfo(msg=(
            'camera_bringup: starting fisheye and RealSense from manager '
            'run_multi_camera.launch.py')),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(fisheye_launch),
            launch_arguments={
                'config_file': LaunchConfiguration('fisheye_config_file'),
                'log_level': log_level,
            }.items(),
            condition=IfCondition(launch_fisheye),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(realsense_launch),
            launch_arguments={
                'config_file': LaunchConfiguration('realsense_config_file'),
                'log_level': log_level,
            }.items(),
            condition=IfCondition(launch_realsense),
        ),
    ])
