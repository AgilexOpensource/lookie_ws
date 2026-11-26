#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "image_transport/simple_publisher_plugin.hpp"
#include "opencv2/core/mat.hpp"
#include "rclcpp/clock.hpp"
#include "rclcpp/logger.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"

namespace camera_compress_transport
{

class VaapiJpegEncoder;

class VaapiPublisher
  : public image_transport::SimplePublisherPlugin<sensor_msgs::msg::CompressedImage>
{
public:
  VaapiPublisher() = default;
  ~VaapiPublisher() override;

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
  bool encodeColor(const cv::Mat & bgr, std::vector<uint8_t> & output) const;

  int jpeg_quality_{90};
  int png_level_{1};
  rclcpp::Logger logger_{rclcpp::get_logger("vaapi_transport")};
  rclcpp::Clock::SharedPtr clock_;

  mutable std::mutex encoder_mutex_;
  mutable std::unique_ptr<VaapiJpegEncoder> encoder_;
  mutable bool vaapi_failed_{false};
  mutable int failed_width_{0};
  mutable int failed_height_{0};
};

}  // namespace camera_compress_transport
