#include "camera_compress_transport/depth_png_compress_publisher.hpp"

#include <string>
#include <vector>

#include "cv_bridge/cv_bridge.h"
#include "opencv2/imgcodecs.hpp"
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

std::string DepthPngCompressPublisher::getTransportName() const
{
  return "depth_png_compress";
}

void DepthPngCompressPublisher::advertiseImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  rmw_qos_profile_t custom_qos)
{
  SimplePublisherPlugin::advertiseImpl(node, base_topic, custom_qos);
  logger_ = node->get_logger();
  clock_ = node->get_clock();
}

void DepthPngCompressPublisher::publish(
  const sensor_msgs::msg::Image & message,
  const PublishFn & publish_fn) const
{
  if (!isDepth16(message.encoding)) {
    RCLCPP_ERROR_THROTTLE(
      logger_, *clock_, 5000,
      "depth_png_compress skips %s. Supported inputs are 16UC1 and mono16.",
      message.encoding.c_str());
    return;
  }

  try {
    const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(
      message, nullptr, message.encoding);
    const cv::Mat & depth = cv_ptr->image;
    if (depth.empty() || depth.type() != CV_16UC1) {
      RCLCPP_ERROR_THROTTLE(
        logger_, *clock_, 5000, "depth_png_compress expected a 16-bit image");
      return;
    }

    sensor_msgs::msg::CompressedImage compressed;
    compressed.header = message.header;
    compressed.format = message.encoding + "; png compressed " + message.encoding;

    // Compression level resets the zlib strategy, so RLE must come after it.
    const std::vector<int> params = {
      cv::IMWRITE_PNG_COMPRESSION, 1,
      cv::IMWRITE_PNG_STRATEGY, cv::IMWRITE_PNG_STRATEGY_RLE
    };
    if (!cv::imencode(".png", depth, compressed.data, params) || compressed.data.empty()) {
      RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_png_compress encode failed");
      return;
    }

    RCLCPP_INFO_ONCE(
      logger_, "depth_png_compress encoding %s (%dx%d)",
      message.encoding.c_str(), depth.cols, depth.rows);
    publish_fn(compressed);
  } catch (const cv_bridge::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_png_compress: %s", ex.what());
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_png_compress: %s", ex.what());
  } catch (const std::runtime_error & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "depth_png_compress: %s", ex.what());
  }
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::DepthPngCompressPublisher,
  image_transport::PublisherPlugin)
