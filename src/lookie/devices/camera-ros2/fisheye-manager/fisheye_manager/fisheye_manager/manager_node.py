import rclpy
from rclpy.node import Node

from .manager_core import ManagerCore


class FisheyeManagerNode(Node):
    def __init__(self):
        super().__init__('fisheye_manager')
        self.core = ManagerCore(self)
        self.core.configure()
        self.core.set_active(True)

    def destroy_node(self):
        self.core.cleanup()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FisheyeManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
