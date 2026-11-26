#include "camera_compress_transport/depth_rvl_compress_subscriber.hpp"

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

constexpr uint32_t kMaxDimension = 8192;

std::string encodingFromFormat(const std::string & format)
{
  const auto split = format.find(';');
  if (split == std::string::npos || format.find("rvl") == std::string::npos) {
    return std::string();
  }
  return format.substr(0, split);
}

}  // namespace

std::string DepthRvlCompressSubscriber::getTransportName() const
{
  return "depth_rvl_compress";
}

void DepthRvlCompressSubscriber::subscribeImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  const Callback & callback,
  rmw_qos_profile_t custom_qos)
{
  logger_ = node->get_logger();
  SimpleSubscriberPlugin::subscribeImpl(node, base_topic, callback, custom_qos);
}

void DepthRvlCompressSubscriber::subscribeImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  const Callback & callback,
  rmw_qos_profile_t custom_qos,
  rclcpp::SubscriptionOptions options)
{
  logger_ = node->get_logger();
  SimpleSubscriberPlugin::subscribeImplWithOptions(
    node, base_topic, callback, custom_qos, options);
}

void DepthRvlCompressSubscriber::internalCallback(
  const sensor_msgs::msg::CompressedImage::ConstSharedPtr & message,
  const Callback & user_cb)
{
  const std::string encoding = encodingFromFormat(message->format);
  if (encoding.empty()) {
    RCLCPP_ERROR(
      logger_, "depth_rvl_compress cannot decode format '%s'", message->format.c_str());
    return;
  }

  constexpr size_t kHeaderBytes = sizeof(uint32_t) * 2;
  if (message->data.size() < kHeaderBytes ||
    (message->data.size() - kHeaderBytes) % sizeof(uint32_t) != 0)
  {
    RCLCPP_ERROR(logger_, "depth_rvl_compress received a truncated packet");
    return;
  }

  uint32_t width = 0;
  uint32_t height = 0;
  std::memcpy(&width, message->data.data(), sizeof(width));
  std::memcpy(&height, message->data.data() + sizeof(width), sizeof(height));
  if (width == 0 || height == 0 || width > kMaxDimension || height > kMaxDimension) {
    RCLCPP_ERROR(
      logger_, "depth_rvl_compress received an invalid size %ux%u", width, height);
    return;
  }

  const auto pixels64 = static_cast<uint64_t>(width) * height;
  const int word_count = static_cast<int>((message->data.size() - kHeaderBytes) / sizeof(uint32_t));
  std::vector<uint32_t> words(static_cast<size_t>(word_count));
  std::memcpy(
    words.data(), message->data.data() + kHeaderBytes, words.size() * sizeof(uint32_t));

  cv::Mat depth(static_cast<int>(height), static_cast<int>(width), CV_16UC1);
  if (!RvlCodec::decompress(
      words.data(), word_count, depth.ptr<uint16_t>(), static_cast<int>(pixels64)))
  {
    RCLCPP_ERROR(logger_, "depth_rvl_compress decode failed");
    return;
  }

  cv_bridge::CvImage image;
  image.header = message->header;
  image.encoding = encoding;
  image.image = depth;
  user_cb(image.toImageMsg());
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::DepthRvlCompressSubscriber,
  image_transport::SubscriberPlugin)
