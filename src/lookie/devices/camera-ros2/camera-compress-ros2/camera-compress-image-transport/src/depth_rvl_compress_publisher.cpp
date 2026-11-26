#include "camera_compress_transport/depth_rvl_compress_publisher.hpp"

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "camera_compress_transport/rvl_codec.hpp"
#include "cv_bridge/cv_bridge.h"
#include "pluginlib/class_list_macros.hpp"
#include "sensor_msgs/image_encodings.hpp"

namespace camera_compress_transport
{
namespace
{

namespace enc = sensor_msgs::image_encodings;

bool isDepth16(const std::string & encoding)
{
  return encoding == enc::TYPE_16UC1 || encoding == enc::MONO16;
}

}  // namespace

std::string DepthRvlCompressPublisher::getTransportName() const
{
  return "depth_rvl_compress";
}

void DepthRvlCompressPublisher::advertiseImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  rmw_qos_profile_t custom_qos)
{
  SimplePublisherPlugin::advertiseImpl(node, base_topic, custom_qos);
  logger_ = node->get_logger();
  clock_ = node->get_clock();
}

void DepthRvlCompressPublisher::publish(
  const sensor_msgs::msg::Image & message,
  const PublishFn & publish_fn) const
{
  if (!isDepth16(message.encoding)) {
    RCLCPP_ERROR_THROTTLE(
      logger_, *clock_, 5000,
      "depth_rvl_compress skips %s. Supported inputs are 16UC1 and mono16.",
      message.encoding.c_str());
    return;
  }

  try {
    const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(
      message, nullptr, message.encoding);
    const cv::Mat & depth = cv_ptr->image;
    if (depth.empty() || depth.type() != CV_16UC1) {
      RCLCPP_ERROR_THROTTLE(
        logger_, *clock_, 5000, "depth_rvl_compress expected a 16-bit image");
      return;
    }

    const cv::Mat continuous = depth.isContinuous() ? depth : depth.clone();
    const int pixels = continuous.rows * continuous.cols;
    if (pixels <= 0) {
      return;
    }

    // Four bytes per pixel covers the worst-case RVL expansion plus the final word.
    thread_local std::vector<uint32_t> words;
    const size_t word_count = static_cast<size_t>(pixels) + 8;
    if (words.size() < word_count) {
      words.resize(word_count);
    }

    const int compressed_bytes = RvlCodec::compress(
      continuous.ptr<uint16_t>(), words.data(), static_cast<int>(word_count), pixels);
    if (compressed_bytes < 0) {
      RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_rvl_compress encode failed");
      return;
    }

    sensor_msgs::msg::CompressedImage compressed;
    compressed.header = message.header;
    compressed.format = message.encoding + "; rvl compressed " + message.encoding;
    compressed.data.resize(sizeof(uint32_t) * 2 + static_cast<size_t>(compressed_bytes));

    const auto width = static_cast<uint32_t>(continuous.cols);
    const auto height = static_cast<uint32_t>(continuous.rows);
    std::memcpy(compressed.data.data(), &width, sizeof(width));
    std::memcpy(compressed.data.data() + sizeof(width), &height, sizeof(height));
    std::memcpy(
      compressed.data.data() + sizeof(width) + sizeof(height),
      words.data(),
      static_cast<size_t>(compressed_bytes));

    RCLCPP_INFO_ONCE(
      logger_, "depth_rvl_compress encoding %s (%ux%u)",
      message.encoding.c_str(), width, height);
    publish_fn(compressed);
  } catch (const cv_bridge::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_rvl_compress: %s", ex.what());
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_rvl_compress: %s", ex.what());
  } catch (const std::runtime_error & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_rvl_compress: %s", ex.what());
  }
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::DepthRvlCompressPublisher,
  image_transport::PublisherPlugin)
