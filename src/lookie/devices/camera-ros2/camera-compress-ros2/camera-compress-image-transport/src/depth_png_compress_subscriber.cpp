#include "camera_compress_transport/depth_png_compress_subscriber.hpp"

#include <string>

#include "cv_bridge/cv_bridge.h"
#include "opencv2/imgcodecs.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "sensor_msgs/image_encodings.hpp"

namespace camera_compress_transport
{
namespace
{

namespace enc = sensor_msgs::image_encodings;

std::string encodingFromFormat(const std::string & format)
{
  const auto split = format.find(';');
  if (split == std::string::npos || format.find("png") == std::string::npos) {
    return std::string();
  }
  const std::string encoding = format.substr(0, split);
  if (encoding != enc::TYPE_16UC1 && encoding != enc::MONO16) {
    return std::string();
  }
  return encoding;
}

}  // namespace

std::string DepthPngCompressSubscriber::getTransportName() const
{
  return "depth_png_compress";
}

void DepthPngCompressSubscriber::subscribeImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  const Callback & callback,
  rmw_qos_profile_t custom_qos)
{
  logger_ = node->get_logger();
  SimpleSubscriberPlugin::subscribeImpl(node, base_topic, callback, custom_qos);
}

void DepthPngCompressSubscriber::subscribeImpl(
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

void DepthPngCompressSubscriber::internalCallback(
  const sensor_msgs::msg::CompressedImage::ConstSharedPtr & message,
  const Callback & user_cb)
{
  const std::string encoding = encodingFromFormat(message->format);
  if (encoding.empty()) {
    RCLCPP_ERROR(
      logger_, "depth_png_compress cannot decode format '%s'", message->format.c_str());
    return;
  }

  cv::Mat decoded;
  try {
    decoded = cv::imdecode(cv::Mat(message->data), cv::IMREAD_UNCHANGED);
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR(logger_, "depth_png_compress decode failed: %s", ex.what());
    return;
  }
  if (decoded.empty() || decoded.type() != CV_16UC1) {
    RCLCPP_ERROR(logger_, "depth_png_compress decode did not produce a 16-bit image");
    return;
  }

  cv_bridge::CvImage image;
  image.header = message->header;
  image.encoding = encoding;
  image.image = decoded;
  user_cb(image.toImageMsg());
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::DepthPngCompressSubscriber,
  image_transport::SubscriberPlugin)
