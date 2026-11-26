#include <cstdlib>
#include <functional>
#include <memory>
#include <string>
#include <vector>
#include <stdexcept>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "sensor_msgs/msg/compressed_image.hpp"
#include "cv_bridge/cv_bridge.h"
#include <opencv2/opencv.hpp>

#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
// sudo apt-get install -y libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev gstreamer1.0-vaapi
/*
13 代用的是 Ubuntu 22.04 自带的 intel-media-va-driver 22.3，能认 i5-13450HX。
Core Ultra 是 Arc 核显（Xe-LPG 或 Xe2），22.3 认不出，初始化会失败，然后退回 libjpeg-turbo。
需要更新的 intel-media-va-driver，一般是 23.4 以后，或者直接用带新驱动的系统。
*/
// ─────────────────────────────────────────────────────────────────────────────
// VA-API 硬件 JPEG 编码器（彩色图专用）
// pipeline: appsrc → videoconvert → vaapijpegenc → appsink
// ─────────────────────────────────────────────────────────────────────────────
class VaapiJpegEncoder {
public:
    VaapiJpegEncoder(int width, int height, int quality)
        : width_(width), height_(height)
    {
        // 构建 pipeline 字符串
        // vaapijpegenc quality 范围 [0, 100]
        std::string pipeline_str =
            "appsrc name=src format=time is-live=true "
            "caps=video/x-raw,format=BGR,width=" + std::to_string(width) +
            ",height=" + std::to_string(height) + ",framerate=0/1 ! "
            "videoconvert ! "
            "video/x-raw,format=NV12 ! "
            "vaapijpegenc quality=" + std::to_string(quality) + " ! "
            "appsink name=sink emit-signals=false sync=false";

        GError* err = nullptr;
        pipeline_ = gst_parse_launch(pipeline_str.c_str(), &err);
        if (!pipeline_ || err) {
            std::string msg = err ? err->message : "unknown";
            if (err) g_error_free(err);
            throw std::runtime_error("GStreamer pipeline failed: " + msg);
        }

        src_  = GST_APP_SRC(gst_bin_get_by_name(GST_BIN(pipeline_), "src"));
        sink_ = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(pipeline_), "sink"));

        gst_element_set_state(pipeline_, GST_STATE_PLAYING);
    }

    ~VaapiJpegEncoder() {
        if (pipeline_) {
            gst_element_set_state(pipeline_, GST_STATE_NULL);
            gst_object_unref(pipeline_);
        }
        if (src_)  gst_object_unref(src_);
        if (sink_) gst_object_unref(sink_);
    }

    // 编码一帧，结果写入 output；成功返回 true
    bool encode(const cv::Mat& bgr_image, std::vector<uint8_t>& output) {
        const size_t data_size = bgr_image.total() * bgr_image.elemSize();

        // 将图像数据包装进 GstBuffer（零拷贝包装，不转移所有权）
        GstBuffer* buf = gst_buffer_new_wrapped_full(
            GST_MEMORY_FLAG_READONLY,
            const_cast<uint8_t*>(bgr_image.data),
            data_size, 0, data_size,
            nullptr, nullptr);

        if (gst_app_src_push_buffer(src_, buf) != GST_FLOW_OK) {
            return false;
        }

        // 等待编码结果（超时 200ms）
        GstSample* sample = gst_app_sink_try_pull_sample(sink_, 200 * GST_MSECOND);
        if (!sample) return false;

        GstBuffer* out_buf = gst_sample_get_buffer(sample);
        GstMapInfo map;
        gst_buffer_map(out_buf, &map, GST_MAP_READ);

        output.assign(map.data, map.data + map.size);

        gst_buffer_unmap(out_buf, &map);
        gst_sample_unref(sample);
        return true;
    }

    int width()  const { return width_; }
    int height() const { return height_; }

private:
    GstElement*  pipeline_{nullptr};
    GstAppSrc*   src_{nullptr};
    GstAppSink*  sink_{nullptr};
    int width_, height_;
};

// ─────────────────────────────────────────────────────────────────────────────
// vaapi_compress 节点
// ─────────────────────────────────────────────────────────────────────────────
class ImageCompressor : public rclcpp::Node {
public:
    ImageCompressor() : Node("vaapi_compress") {
        // ── 参数声明 ──────────────────────────────────────────────────────────
        this->declare_parameter<std::string>("topic_namespace", "camera_left");
        this->declare_parameter<int>("jpeg_quality",    90);
        this->declare_parameter<int>("png_compression",  1);

        const std::string ns = this->get_parameter("topic_namespace").as_string();
        jpeg_quality_        = this->get_parameter("jpeg_quality").as_int();
        png_compression_     = this->get_parameter("png_compression").as_int();

        depth_params_ = {cv::IMWRITE_PNG_COMPRESSION, png_compression_};

        RCLCPP_INFO(this->get_logger(),
            "ns=%s  jpeg_quality=%d  png_compression=%d",
            ns.c_str(), jpeg_quality_, png_compression_);

        // ── 话题名称 ──────────────────────────────────────────────────────────
        const std::string color_topic = "/" + ns + "/color/image_rect_raw";
        const std::string depth_topic = "/" + ns + "/aligned_depth_to_color/image_raw";

        // ── QoS：对齐 Python 版（RELIABLE + VOLATILE + depth=30）─────────────
        auto sub_qos = rclcpp::QoS(rclcpp::KeepLast(30));
        auto pub_qos = rclcpp::QoS(rclcpp::KeepLast(30));

        // ── 发布者 ────────────────────────────────────────────────────────────
        color_pub_ = this->create_publisher<sensor_msgs::msg::CompressedImage>(
            color_topic + "/compressed", pub_qos);
        depth_pub_ = this->create_publisher<sensor_msgs::msg::CompressedImage>(
            depth_topic + "/compressed", pub_qos);

        // ── 回调组（组间可并行） ───────────────────────────────────────────────
        cg_color_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
        cg_depth_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);

        rclcpp::SubscriptionOptions color_opt, depth_opt;
        color_opt.callback_group = cg_color_;
        depth_opt.callback_group = cg_depth_;

        // ── 订阅者 ────────────────────────────────────────────────────────────
        color_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
            color_topic, sub_qos,
            std::bind(&ImageCompressor::color_callback, this, std::placeholders::_1),
            color_opt);

        depth_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
            depth_topic, sub_qos,
            std::bind(&ImageCompressor::depth_callback, this, std::placeholders::_1),
            depth_opt);
    }

private:
    // 首帧到来时延迟初始化硬件编码器（此时才知道分辨率）
    void ensure_encoder(int width, int height) {
        if (vaapi_encoder_ &&
            vaapi_encoder_->width()  == width &&
            vaapi_encoder_->height() == height) {
            return;  // 已初始化且分辨率一致
        }
        try {
            vaapi_encoder_ = std::make_unique<VaapiJpegEncoder>(width, height, jpeg_quality_);
            RCLCPP_INFO(this->get_logger(),
                "VA-API JPEG encoder initialized (%dx%d, quality=%d)",
                width, height, jpeg_quality_);
        } catch (const std::exception& e) {
            // 硬件编码器初始化失败，回退到 libjpeg-turbo 软件编码
            vaapi_encoder_.reset();
            RCLCPP_WARN(this->get_logger(),
                "VA-API init failed (%s), falling back to libjpeg-turbo.", e.what());
        }
    }

    // ── 彩色图像回调：优先走 VA-API 硬件，失败自动回退软件 ───────────────────
    void color_callback(const sensor_msgs::msg::Image::SharedPtr msg) {
        try {
            const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(msg, "bgr8");
            ensure_encoder(cv_ptr->image.cols, cv_ptr->image.rows);

            bool encoded = false;

            if (vaapi_encoder_) {
                encoded = vaapi_encoder_->encode(cv_ptr->image, color_buffer_);
                if (!encoded) {
                    RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
                        "VA-API encode failed, falling back to software.");
                }
            }

            if (!encoded) {
                // 软件回退：libjpeg-turbo
                const std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, jpeg_quality_};
                if (!cv::imencode(".jpg", cv_ptr->image, color_buffer_, params)) {
                    RCLCPP_WARN(this->get_logger(), "Software JPEG encoding failed.");
                    return;
                }
            }

            auto out = std::make_unique<sensor_msgs::msg::CompressedImage>();
            out->header = msg->header;
            out->format = "jpeg";
            out->data   = color_buffer_;
            color_pub_->publish(std::move(out));

        } catch (const std::exception& e) {
            RCLCPP_ERROR(this->get_logger(), "Color callback error: %s", e.what());
        }
    }

    // ── 深度图像回调：PNG level 1（无损，格式标准，foxglove 兼容）─────────────
    void depth_callback(const sensor_msgs::msg::Image::SharedPtr msg) {
        try {
            const cv_bridge::CvImageConstPtr cv_ptr = cv_bridge::toCvShare(msg, "16UC1");

            if (!cv::imencode(".png", cv_ptr->image, depth_buffer_, depth_params_)) {
                RCLCPP_WARN(this->get_logger(), "PNG encoding failed.");
                return;
            }

            auto out = std::make_unique<sensor_msgs::msg::CompressedImage>();
            out->header = msg->header;
            out->format = "png";
            out->data   = depth_buffer_;
            depth_pub_->publish(std::move(out));

        } catch (const std::exception& e) {
            RCLCPP_ERROR(this->get_logger(), "Depth callback error: %s", e.what());
        }
    }

    // ── 成员变量 ──────────────────────────────────────────────────────────────
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr color_sub_;
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr depth_sub_;
    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr color_pub_;
    rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr depth_pub_;
    rclcpp::CallbackGroup::SharedPtr cg_color_;
    rclcpp::CallbackGroup::SharedPtr cg_depth_;

    std::unique_ptr<VaapiJpegEncoder> vaapi_encoder_;   // 硬件编码器（延迟初始化）

    int jpeg_quality_{90};
    int png_compression_{1};
    std::vector<int> depth_params_;

    std::vector<uint8_t> color_buffer_;
    std::vector<uchar>   depth_buffer_;
};

// ─────────────────────────────────────────────────────────────────────────────
int main(int argc, char** argv) {
    // 这台机器同时有 Intel 核显和 NVIDIA。不指定驱动时，gstreamer-vaapi
    // 只注册 decode/postproc/sink，不会注册 vaapijpegenc。13 代 Intel 要用 iHD。
    if (const char* driver = std::getenv("LIBVA_DRIVER_NAME");
        driver == nullptr || driver[0] == '\0') {
        setenv("LIBVA_DRIVER_NAME", "iHD", 0);
    }
    gst_init(&argc, &argv);   // GStreamer 初始化必须在 rclcpp 之前
    rclcpp::init(argc, argv);

    auto node = std::make_shared<ImageCompressor>();

    rclcpp::executors::MultiThreadedExecutor executor(rclcpp::ExecutorOptions(), 2);
    executor.add_node(node);
    executor.spin();

    rclcpp::shutdown();
    gst_deinit();
    return 0;
}
