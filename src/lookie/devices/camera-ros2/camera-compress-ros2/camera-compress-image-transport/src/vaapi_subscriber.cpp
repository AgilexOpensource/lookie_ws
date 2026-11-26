#include "camera_compress_transport/vaapi_subscriber.hpp"

#include <string>

#include "cv_bridge/cv_bridge.h"
#include "opencv2/imgcodecs.hpp"
#include "opencv2/imgproc.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "sensor_msgs/image_encodings.hpp"

namespace camera_compress_transport
{
namespace
{

namespace enc = sensor_msgs::image_encodings;

void restoreColor(const std::string & format, const std::string & encoding, cv::Mat & image)
{
  if (!enc::isColor(encoding)) {
    return;
  }
  const bool compressed_bgr = format.find("compressed bgr") != std::string::npos;
  if (!compressed_bgr) {
    return;
  }
  if (encoding == enc::RGB8) {
    cv::cvtColor(image, image, cv::COLOR_BGR2RGB);
  } else if (encoding == enc::RGBA8) {
    cv::cvtColor(image, image, cv::COLOR_BGR2RGBA);
  } else if (encoding == enc::BGRA8) {
    cv::cvtColor(image, image, cv::COLOR_BGR2BGRA);
  }
}

std::string encodingFromDecoded(const cv::Mat & image, const std::string & format)
{
  const auto split = format.find(';');
  if (split != std::string::npos) {
    return format.substr(0, split);
  }
  if (image.channels() == 1 && image.depth() == CV_16U) {
    return enc::TYPE_16UC1;
  }
  if (image.channels() == 1) {
    return enc::MONO8;
  }
  if (image.channels() == 3) {
    return enc::BGR8;
  }
  return std::string();
}

}  // namespace

std::string VaapiSubscriber::getTransportName() const
{
  return "vaapi_compress";
}

void VaapiSubscriber::subscribeImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  const Callback & callback,
  rmw_qos_profile_t custom_qos)
{
  logger_ = node->get_logger();
  SimpleSubscriberPlugin::subscribeImpl(node, base_topic, callback, custom_qos);
}

void VaapiSubscriber::subscribeImpl(
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

void VaapiSubscriber::internalCallback(
  const sensor_msgs::msg::CompressedImage::ConstSharedPtr & message,
  const Callback & user_cb)
{
  cv::Mat decoded;
  try {
    decoded = cv::imdecode(cv::Mat(message->data), cv::IMREAD_UNCHANGED);
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR(logger_, "vaapi decode failed: %s", ex.what());
    return;
  }
  if (decoded.empty()) {
    RCLCPP_ERROR(logger_, "vaapi decode produced an empty image");
    return;
  }

  cv_bridge::CvImage image;
  image.header = message->header;
  image.image = decoded;
  image.encoding = encodingFromDecoded(decoded, message->format);
  if (image.encoding.empty()) {
    RCLCPP_ERROR(
      logger_, "vaapi cannot infer encoding from format '%s'", message->format.c_str());
    return;
  }
  restoreColor(message->format, image.encoding, image.image);
  user_cb(image.toImageMsg());
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::VaapiSubscriber,
  image_transport::SubscriberPlugin)
