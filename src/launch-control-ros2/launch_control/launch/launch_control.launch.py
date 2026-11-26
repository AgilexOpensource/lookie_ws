from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='launch_control',
            executable='launch_control.py',
            name='launch_control_node',
            output='screen',
            emulate_tty=True,   # 让 Python 以为是终端，从而用行缓冲
        )
    ])
