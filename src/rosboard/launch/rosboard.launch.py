from launch import LaunchDescription
from launch.actions import ExecuteProcess
from ament_index_python.packages import get_package_prefix


def generate_launch_description():
    startup = get_package_prefix('rosboard') + '/lib/rosboard/startup'
    return LaunchDescription([
        ExecuteProcess(cmd=[startup], output='screen'),
    ])
