from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_file = LaunchConfiguration("params_file")
    node_name = LaunchConfiguration("node_name")

    default_params_file = PathJoinSubstitution(
        [FindPackageShare("hi04_ros"), "config", "hi04.yaml"]
    )

    declared_args = [
        DeclareLaunchArgument(
            "params_file",
            default_value=default_params_file,
            description="Path to the HI04 ROS parameter YAML file.",
        ),
        DeclareLaunchArgument(
            "node_name",
            default_value="hi04_node",
            description="ROS node name for the HI04 driver.",
        ),
    ]

    hi04_node = Node(
        package="hi04_ros",
        executable="hi04_node",
        name=node_name,
        output="screen",
        parameters=[params_file],
    )

    return LaunchDescription(declared_args + [hi04_node])
