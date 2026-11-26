#include "camera_compress_transport/vaapi_publisher.hpp"

#include <algorithm>
#include <cstdlib>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "cv_bridge/cv_bridge.h"
#include "gst/app/gstappsink.h"
#include "gst/app/gstappsrc.h"
#include "gst/gst.h"
#include "opencv2/imgcodecs.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "rclcpp/exceptions/exceptions.hpp"
#include "sensor_msgs/image_encodings.hpp"

namespace camera_compress_transport
{
namespace
{

namespace enc = sensor_msgs::image_encodings;

void ensureGstreamer()
{
  static std::once_flag once;
  std::call_once(once, []() {
    const char * driver = std::getenv("LIBVA_DRIVER_NAME");
    if (driver == nullptr || driver[0] == '\0') {
      setenv("LIBVA_DRIVER_NAME", "iHD", 0);
    }
    gst_init(nullptr, nullptr);
  });
}

std::string parameterBaseName(rclcpp::Node * node, const std::string & base_topic)
{
  const auto ns_len = node->get_effective_namespace().length();
  std::string name = base_topic.size() > ns_len ? base_topic.substr(ns_len) : base_topic;
  std::replace(name.begin(), name.end(), '/', '.');
  if (!name.empty() && name.front() == '.') {
    name.erase(name.begin());
  }
  return name + ".vaapi_compress";
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

class VaapiJpegEncoder
{
public:
  VaapiJpegEncoder(int width, int height, int quality)
  : width_(width), height_(height)
  {
    ensureGstreamer();
    const std::string pipeline_str =
      "appsrc name=src format=time is-live=true "
      "caps=video/x-raw,format=BGR,width=" + std::to_string(width) +
      ",height=" + std::to_string(height) + ",framerate=0/1 ! "
      "videoconvert ! "
      "video/x-raw,format=NV12 ! "
      "vaapijpegenc quality=" + std::to_string(quality) + " ! "
      "appsink name=sink emit-signals=false sync=false";

    GError * err = nullptr;
    pipeline_ = gst_parse_launch(pipeline_str.c_str(), &err);
    if (!pipeline_ || err) {
      const std::string msg = err ? err->message : "unknown";
      if (err) {
        g_error_free(err);
      }
      throw std::runtime_error("GStreamer pipeline failed: " + msg);
    }

    src_ = GST_APP_SRC(gst_bin_get_by_name(GST_BIN(pipeline_), "src"));
    sink_ = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(pipeline_), "sink"));
    gst_element_set_state(pipeline_, GST_STATE_PLAYING);
  }

  ~VaapiJpegEncoder()
  {
    if (pipeline_) {
      gst_element_set_state(pipeline_, GST_STATE_NULL);
      gst_object_unref(pipeline_);
    }
    if (src_) {
      gst_object_unref(src_);
    }
    if (sink_) {
      gst_object_unref(sink_);
    }
  }

  VaapiJpegEncoder(const VaapiJpegEncoder &) = delete;
  VaapiJpegEncoder & operator=(const VaapiJpegEncoder &) = delete;

  bool encode(const cv::Mat & bgr_image, std::vector<uint8_t> & output)
  {
    const size_t data_size = bgr_image.total() * bgr_image.elemSize();
    GstBuffer * buf = gst_buffer_new_wrapped_full(
      GST_MEMORY_FLAG_READONLY,
      const_cast<uint8_t *>(bgr_image.data),
      data_size, 0, data_size,
      nullptr, nullptr);
    if (gst_app_src_push_buffer(src_, buf) != GST_FLOW_OK) {
      return false;
    }

    GstSample * sample = gst_app_sink_try_pull_sample(sink_, 200 * GST_MSECOND);
    if (!sample) {
      return false;
    }

    GstBuffer * out_buf = gst_sample_get_buffer(sample);
    GstMapInfo map;
    gst_buffer_map(out_buf, &map, GST_MAP_READ);
    output.assign(map.data, map.data + map.size);
    gst_buffer_unmap(out_buf, &map);
    gst_sample_unref(sample);
    return !output.empty();
  }

  int width() const {return width_;}
  int height() const {return height_;}

private:
  GstElement * pipeline_{nullptr};
  GstAppSrc * src_{nullptr};
  GstAppSink * sink_{nullptr};
  int width_;
  int height_;
};

VaapiPublisher::~VaapiPublisher() = default;

std::string VaapiPublisher::getTransportName() const
{
  return "vaapi_compress";
}

void VaapiPublisher::advertiseImpl(
  rclcpp::Node * node,
  const std::string & base_topic,
  rmw_qos_profile_t custom_qos)
{
  SimplePublisherPlugin::advertiseImpl(node, base_topic, custom_qos);
  logger_ = node->get_logger();
  clock_ = node->get_clock();

  const std::string prefix = parameterBaseName(node, base_topic);

  rcl_interfaces::msg::ParameterDescriptor jpeg_description;
  jpeg_description.description = "JPEG quality for VA-API color encoding";
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

bool VaapiPublisher::encodeColor(const cv::Mat & bgr, std::vector<uint8_t> & output) const
{
  std::lock_guard<std::mutex> lock(encoder_mutex_);
  const int width = bgr.cols;
  const int height = bgr.rows;
  if (vaapi_failed_ && failed_width_ == width && failed_height_ == height) {
    return false;
  }

  if (!encoder_ || encoder_->width() != width || encoder_->height() != height) {
    try {
      encoder_ = std::make_unique<VaapiJpegEncoder>(width, height, jpeg_quality_);
      vaapi_failed_ = false;
      RCLCPP_INFO(
        logger_, "VA-API JPEG encoder initialized (%dx%d, quality=%d)",
        width, height, jpeg_quality_);
    } catch (const std::exception & ex) {
      encoder_.reset();
      vaapi_failed_ = true;
      failed_width_ = width;
      failed_height_ = height;
      RCLCPP_WARN(
        logger_, "VA-API init failed (%s), falling back to libjpeg-turbo.", ex.what());
      return false;
    }
  }

  if (encoder_->encode(bgr, output)) {
    return true;
  }
  RCLCPP_WARN_THROTTLE(
    logger_, *clock_, 5000, "VA-API encode failed, falling back to software.");
  return false;
}

void VaapiPublisher::publish(
  const sensor_msgs::msg::Image & message,
  const PublishFn & publish_fn) const
{
  sensor_msgs::msg::CompressedImage compressed;
  compressed.header = message.header;

  try {
    if (isDepth16(message.encoding)) {
      const std::vector<int> params = {cv::IMWRITE_PNG_COMPRESSION, png_level_};
      compressed.format = message.encoding + "; png compressed " + message.encoding;
      const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(
        message, nullptr, message.encoding);
      if (!cv::imencode(".png", cv_ptr->image, compressed.data, params) || compressed.data.empty()) {
        RCLCPP_ERROR_THROTTLE(
          logger_, *clock_, 5000, "vaapi png encode failed for %s", message.encoding.c_str());
        return;
      }
    } else if (isJpegSource(message.encoding)) {
      const std::string target = enc::isMono(message.encoding) ? enc::MONO8 : enc::BGR8;
      compressed.format = message.encoding + "; jpeg compressed " + target;
      const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(message, nullptr, target);
      bool encoded = false;
      if (target == enc::BGR8) {
        std::vector<uint8_t> encoded_bytes;
        encoded = encodeColor(cv_ptr->image, encoded_bytes);
        if (encoded) {
          compressed.data = std::move(encoded_bytes);
        }
      }
      if (!encoded) {
        const std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, jpeg_quality_};
        if (!cv::imencode(".jpg", cv_ptr->image, compressed.data, params) || compressed.data.empty()) {
          RCLCPP_ERROR_THROTTLE(
            logger_, *clock_, 5000, "vaapi jpeg encode failed for %s", message.encoding.c_str());
          return;
        }
      }
    } else {
      RCLCPP_ERROR_THROTTLE(
        logger_, *clock_, 5000,
        "vaapi skips encoding %s. Supported inputs are 8-bit color/mono and 16UC1/mono16.",
        message.encoding.c_str());
      return;
    }
  } catch (const cv_bridge::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "vaapi: %s", ex.what());
    return;
  } catch (const cv::Exception & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "vaapi: %s", ex.what());
    return;
  } catch (const std::runtime_error & ex) {
    RCLCPP_ERROR_THROTTLE(logger_, *clock_, 5000, "vaapi: %s", ex.what());
    return;
  }

  publish_fn(compressed);
}

}  // namespace camera_compress_transport

PLUGINLIB_EXPORT_CLASS(
  camera_compress_transport::VaapiPublisher,
  image_transport::PublisherPlugin)
