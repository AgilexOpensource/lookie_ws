from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    camera_alias = LaunchConfiguration("camera_alias")
    camera_fps = LaunchConfiguration("camera_fps")
    camera_height = LaunchConfiguration("camera_height")
    camera_width = LaunchConfiguration("camera_width")
    camera_frame_id = LaunchConfiguration("camera_frame_id")
    enable_fps_log = LaunchConfiguration("enable_fps_log")
    reconnect_interval = LaunchConfiguration("reconnect_interval")

    return LaunchDescription([
        DeclareLaunchArgument("camera_alias", default_value="fisheye"),
        DeclareLaunchArgument("camera_fps", default_value="30"),
        DeclareLaunchArgument("camera_height", default_value="480"),
        DeclareLaunchArgument("camera_width", default_value="640"),
        DeclareLaunchArgument("camera_frame_id", default_value="camera_fisheye"),
        DeclareLaunchArgument("enable_fps_log", default_value="false"),
        DeclareLaunchArgument("reconnect_interval", default_value="2.0"),
        Node(
            package="fisheye_ros2",
            executable="read_camera_node.py",
            output="screen",
            emulate_tty=True,
            parameters=[{
                "camera_alias": camera_alias,
                "camera_fps": camera_fps,
                "camera_height": camera_height,
                "camera_width": camera_width,
                "camera_frame_id": camera_frame_id,
                "enable_fps_log": enable_fps_log,
                "reconnect_interval": reconnect_interval,
            }],
        ),
    ])
