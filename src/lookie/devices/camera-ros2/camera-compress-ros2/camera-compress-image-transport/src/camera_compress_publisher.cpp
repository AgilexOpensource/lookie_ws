#include "camera_compress_transport/camera_compress_publisher.hpp"

#include <algorithm>
#include <string>
#include <vector>

#include "cv_bridge/cv_bridge.h"
#include "opencv2/imgcodecs.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "rclcpp/exceptions/exceptions.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"

namespace camera_compress_transport
{
namespace
{

namespace enc = sensor_msgs::image_encodings;

std::string parameterBaseName(rclcpp::Node * node, const std::string & base_topic)
{
  const auto ns_len = node->get_effective_namespace().length();
  std::string name = base_topic.size() > ns_len ? base_topic.substr(ns_len) : base_topic;
  std::replace(name.begin(), name.end(), '/', '.');
  if (!name.empty() && name.front() == '.') {
    name.erase(name.begin());
  }
  return name + ".camera_compress";
}

template<typename T>
T declareOrGet(
  rclcpp::Node * node,
  const std::string & name,
  T default_value,
  const rcl_interfaces::msg::ParameterDescriptor & description,
  const rclcpp::Logger & logger)
{
  try {
    return node->declare_parameter<T>(name, default_value, description);
  } catch (const rclcpp::exceptions::ParameterAlreadyDeclaredException &) {
    RCLCPP_DEBUG(logger, "%s was already declared", name.c_str());
    return node->get_parameter(name).get_value<T>();
  }
}

bool isDepth16(const std::string & encoding)
{
  return encoding == enc::TYPE_16UC1 || encoding == enc::MONO16;
}

bool isJpegSource(const std::string & encoding)
{
  return enc::bitDepth(encoding) == 8 &&
         (enc::isColor(encoding) || enc::isMono(encoding) || enc::isBayer(encoding));
}

}  // namespace

std::string CameraCompressPublisher::getTransportName() const
{
  return "camera_compress";
}

void CameraCompressPublisher::advertiseImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  rmw_qos_profile_t custom_qos)
{
  SimplePublisherPlugin::advertiseImpl(node, base_topic, custom_qos);
  logger_ = node->get_logger();
  clock_ = node->get_clock();

  const std::string prefix = parameterBaseName(node, base_topic);

  rcl_interfaces::msg::ParameterDescriptor jpeg_description;
  jpeg_description.description = "JPEG quality for 8-bit color and mono images";
  rcl_interfaces::msg::IntegerRange jpeg_range;
  jpeg_range.from_value = 1;
  jpeg_range.to_value = 100;
  jpeg_range.step = 1;
  jpeg_description.integer_range.push_back(jpeg_range);
  jpeg_quality_ = static_cast<int>(declareOrGet<int64_t>(
      node, prefix + ".jpeg_quality", 90, jpeg_description, logger_));

  rcl_interfaces::msg::ParameterDescriptor png_description;
  png_description.description = "PNG compression level for 16-bit depth";
  rcl_interfaces::msg::IntegerRange png_range;
  png_range.from_value = 0;
  png_range.to_value = 9;
  png_range.step = 1;
  png_description.integer_range.push_back(png_range);
  png_level_ = static_cast<int>(declareOrGet<int64_t>(
      node, prefix + ".png_level", 1, png_description, logger_));

  jpeg_quality_ = std::clamp(jpeg_quality_, 1, 100);
  png_level_ = std::clamp(png_level_, 0, 9);
}

void CameraCompressPublisher::publish(
  const sensor_msgs::msg::Image & message,
  const PublishFn & publish_fn) const
{
  sensor_msgs::msg::CompressedImage compressed;
  compressed.header = message.header;

  std::string target_encoding;
  std::string extension;
  std::vector<int> params;
  try {
    if (isDepth16(message.encoding)) {
      target_encoding = message.encoding;
      extension = ".png";
      params = {cv::IMWRITE_PNG_COMPRESSION, png_level_};
      compressed.format = message.encoding + "; png compressed " + message.encoding;
    } else if (isJpegSource(message.encoding)) {
      target_encoding = enc::isMono(message.encoding) ? enc::MONO8 : enc::BGR8;
      extension = ".jpg";
      params = {cv::IMWRITE_JPEG_QUALITY, jpeg_quality_};
      compressed.format = message.encoding + "; jpeg compressed " + target_encoding;
    } else {
      RCLCPP_ERROR_THROTTLE(
        logger_, *clock_, 5000,
        "camera_compress skips encoding %s. Supported inputs are 8-bit color/mono and 16UC1/mono16.",
        message.encoding.c_str());
      return;
    }

    const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(
      message, nullptr, target_encoding);
    if (!cv::imencode(extension, cv_ptr->image, compressed.data, params) || compressed.data.empty()) {
      RCLCPP_ERROR_THROTTLE(
        logger_, *clock_, 5000,
        "camera_compress encode failed for %s", message.encoding.c_str());
      return;
    }
  } catch (const cv_bridge::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "camera_compress: %s", ex.what());
    return;
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "camera_compress: %s", ex.what());
    return;
  } catch (const std::runtime_error & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "camera_compress: %s", ex.what());
    return;
  }

  publish_fn(compressed);
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::CameraCompressPublisher,
  image_transport::PublisherPlugin)
