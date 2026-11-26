#pragma once

#include <string>

#include "image_transport/simple_subscriber_plugin.hpp"
#include "rclcpp/logger.hpp"
#include "rclcpp/subscription_options.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"

namespace camera_compress_transport
{

class CameraCompressSubscriber
  : public image_transport::SimpleSubscriberPlugin<sensor_msgs::msg::CompressedImage>
{
public:
  CameraCompressSubscriber() = default;

  std::string getTransportName() const override;

protected:
  void subscribeImpl(
    rclcpp::Node * node,
    const std::string & base_topic,
    const Callback & callback,
    rmw_qos_profile_t custom_qos) override;

  void subscribeImpl(
    rclcpp::Node * node,
    const std::string & base_topic,
    const Callback & callback,
    rmw_qos_profile_t custom_qos,
    rclcpp::SubscriptionOptions options) override;

  void internalCallback(
    const sensor_msgs::msg::CompressedImage::ConstSharedPtr & message,
    const Callback & user_cb) override;

private:
  rclcpp::Logger logger_{rclcpp::get_logger("camera_compress_transport")};
};

}  // namespace camera_compress_transport
