import rclpy
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn

from .manager_core import ManagerCore


class RealSenseLifecycleManagerNode(LifecycleNode):
    def __init__(self):
        super().__init__('realsense_manager')
        self.core = ManagerCore(self)

    def on_configure(self, state):
        try:
            self.core.configure()
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:  # Lifecycle callbacks must report failure instead of exiting.
            self.get_logger().error(f'Configure failed: {exc}')
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state):
        self.core.set_active(True)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state):
        self.core.set_active(False)
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        self.core.cleanup()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state):
        self.core.cleanup()
        return TransitionCallbackReturn.SUCCESS

    def destroy_node(self):
        self.core.cleanup()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RealSenseLifecycleManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
