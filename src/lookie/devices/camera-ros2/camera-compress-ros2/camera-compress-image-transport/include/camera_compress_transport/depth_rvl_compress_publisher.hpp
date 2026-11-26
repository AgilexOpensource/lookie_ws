#pragma once

#include <string>

#include "image_transport/simple_publisher_plugin.hpp"
#include "rclcpp/clock.hpp"
#include "rclcpp/logger.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"

namespace camera_compress_transport
{

class DepthRvlCompressPublisher
  : public image_transport::SimplePublisherPlugin<sensor_msgs::msg::CompressedImage>
{
public:
  DepthRvlCompressPublisher() = default;

  std::string getTransportName() const override;

protected:
  void advertiseImpl(
    rclcpp::Node * node,
    const std::string & base_topic,
    rmw_qos_profile_t custom_qos) override;

  void publish(
    const sensor_msgs::msg::Image & message,
    const PublishFn & publish_fn) const override;

private:
  rclcpp::Logger logger_{rclcpp::get_logger("depth_rvl_compress")};
  rclcpp::Clock::SharedPtr clock_;
};

}  // namespace camera_compress_transport
