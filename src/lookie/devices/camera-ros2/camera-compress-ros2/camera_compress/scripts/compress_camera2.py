#!/usr/bin/env python3
# -*-coding:utf8-*-
Version = "0.0.2"

import rclpy
import rclpy.executors
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage
from cv_bridge import CvBridge
import cv2
import array

class ImageCompressor(Node):
    def __init__(self):
        super().__init__("compress_camera_node")
        
        self.declare_parameter('topic_namespace', "camera_left")
        # self.declare_parameter('topic_namespace', "/camera/camera")
        self.declare_parameter('compress_rgb', True)
        self.declare_parameter('compress_depth', False)
        self.declare_parameter('topic_name', "image_raw")
        self.topic_namespace = self.get_parameter('topic_namespace').get_parameter_value().string_value
        self.compress_rgb = self.get_parameter('compress_rgb').get_parameter_value().bool_value
        self.compress_depth = self.get_parameter('compress_depth').get_parameter_value().bool_value
        self.topic_name = self.get_parameter('topic_name').get_parameter_value().string_value
        self.get_logger().info(f"topic_namespace: {self.topic_namespace}")
        self.get_logger().info(f"compress_rgb: {self.compress_rgb}")
        self.get_logger().info(f"compress_depth: {self.compress_depth}")
        self.get_logger().info(f"topic_name: {self.topic_name}")

        if self.compress_rgb:
            self.get_logger().info(f"start compress rgb image.")
            self.img_bridge = CvBridge()
            self.image_compressed_pub = self.create_publisher(CompressedImage, f'{self.topic_namespace}/color/{self.topic_name}/compressed', 10)
            self.image_sub = self.create_subscription(Image, f'{self.topic_namespace}/color/{self.topic_name}', self.image_callback, rclpy.qos.QoSPresetProfiles.SENSOR_DATA.value)  # 使用传感器数据QoS配置)

        if self.compress_depth:
            self.get_logger().info(f"start compress depth image.")
            self.depth_bridge = CvBridge()
            self.depth_compressed_pub = self.create_publisher(CompressedImage, f'{self.topic_namespace}/aligned_depth_to_color/{self.topic_name}/compressed', 10)
            self.depth_sub = self.create_subscription(Image, f'{self.topic_namespace}/aligned_depth_to_color/{self.topic_name}', self.depth_callback, 10)

    def image_callback(self, msg=Image()):
        cv_image = self.img_bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        ret, jpeg_image = cv2.imencode('.jpg', cv_image, encode_param)
        
        compressed_image_msg = CompressedImage()
        compressed_image_msg.header = msg.header
        compressed_image_msg.format = "jpeg"
        compressed_image_msg.data = array.array('B', jpeg_image.tobytes())
        self.image_compressed_pub.publish(compressed_image_msg)

    def depth_callback(self, msg=Image()):
        cv_depth = self.depth_bridge.imgmsg_to_cv2(msg, desired_encoding="16UC1")
        success, encoded_depth = cv2.imencode(".png", cv_depth, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])

        compressed_msg = CompressedImage()
        compressed_msg.header = msg.header
        compressed_msg.format = "png"
        compressed_msg.data = array.array('B', encoded_depth.tobytes())
        self.depth_compressed_pub.publish(compressed_msg)
    
def main(args=None):
    print("version: %s" % Version)
    rclpy.init(args=args)
    compress_camera_node = ImageCompressor()
    try:
        rclpy.spin(compress_camera_node)
    except KeyboardInterrupt:
        pass    
    finally:
        compress_camera_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == "__main__":
    main()
