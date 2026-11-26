#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include <mutex>
#include <condition_variable>
#include <sstream>
#include <algorithm>
#include <vector>
#include <cctype>
#include <atomic>
#include <std_srvs/srv/trigger.hpp>
#include <std_msgs/msg/bool.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include "installation_rotation.hpp"

#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/magnetic_field.hpp>
#include <sensor_msgs/msg/temperature.hpp>
#include <sensor_msgs/msg/fluid_pressure.hpp>
#include <geometry_msgs/msg/vector3_stamped.hpp>
#include "rclcpp/rclcpp.hpp"

#include <unistd.h>
#include <fcntl.h>
#include <asm/termbits.h>
#include <sys/ioctl.h>

#ifdef __cplusplus
extern "C"{
#endif
#include <poll.h>

#include "hipnuc_dec.h"

#define GRA_ACC          (9.8)
#define DEG_TO_RAD       (0.01745329)
#define UTESLA_TO_TESLA  (0.000001)
#define BUF_SIZE         (1024)
#ifdef __cplusplus
}
#endif



namespace hipnuc_driver
{
	using namespace std::chrono_literals;
	using namespace std;

	class IMUPublisher : public rclcpp::Node
	{
		public:
			
			IMUPublisher(const rclcpp::NodeOptions &options) : Node("IMU_publisher", options)	
			{
				this->declare_parameter<std::string>("serial_port", "/dev/ttyUSB0");
				this->declare_parameter<int>("baud_rate", 115200);
				this->declare_parameter<std::string>("frame_id", "base_link");
				this->declare_parameter<std::string>("imu_topic", "/IMU_data");
				this->declare_parameter<std::string>("euler_topic", "/euler_data");
				this->declare_parameter<std::string>("magnetic_topic", "/magnetic_data");
				this->declare_parameter<std::string>("temperature_topic", "/temperature_data");
				this->declare_parameter<std::string>("pressure_topic", "/pressure_data");
				this->declare_parameter<bool>("imu_switch", true);
				this->declare_parameter<bool>("euler_switch", false);
				this->declare_parameter<bool>("magnetic_switch", false);
				this->declare_parameter<bool>("temperature_switch", false);
				this->declare_parameter<bool>("pressure_switch", false);
				this->declare_parameter<bool>("publish_tf", false);
				this->declare_parameter<std::string>("tf_parent_frame", "world");
				this->declare_parameter<std::string>("tf_child_frame_id", "");

                wait_for_device_timeout = declare_parameter<double>("wait_for_device_timeout", -1.0);
                reconnect_timeout = declare_parameter<double>("reconnect_timeout", 6.0);
                reconnect_attempts = declare_parameter<int>("reconnect_attempts", -1);
                data_timeout = declare_parameter<double>("data_timeout", 2.0);
                const double install_roll = declare_parameter<double>("imu_install_roll_deg", 0.0);
                const double install_pitch = declare_parameter<double>("imu_install_pitch_deg", 0.0);
                const double install_yaw = declare_parameter<double>("imu_install_yaw_deg", 0.0);
                installation_rotation = InstallationRotation(install_roll, install_pitch, install_yaw);
                RCLCPP_INFO(get_logger(), "IMU right-hand attitude calibration RPY (degrees): [%g, %g, %g]",
                            install_roll, install_pitch, install_yaw);
                if (!std::isfinite(wait_for_device_timeout) ||
                    (wait_for_device_timeout < 0 && wait_for_device_timeout != -1.0) ||
                    !std::isfinite(reconnect_timeout) || reconnect_timeout <= 0 ||
                    !std::isfinite(data_timeout) || data_timeout <= 0 || reconnect_attempts < -1) {
                    throw std::invalid_argument("Invalid connection parameters: wait_for_device_timeout must be -1 or >= 0, reconnect_timeout/data_timeout > 0, reconnect_attempts >= -1");
                }

				this->get_parameter("serial_port", serial_port);
				this->get_parameter("baud_rate", baud_rate);
				this->get_parameter("frame_id", frame_id);
				this->get_parameter("imu_topic", imu_topic);
				this->get_parameter("euler_topic", euler_topic);
				this->get_parameter("magnetic_topic", magnetic_topic);
				this->get_parameter("temperature_topic", temperature_topic);
				this->get_parameter("pressure_topic", pressure_topic);
				this->get_parameter("imu_switch", imu_switch);
				this->get_parameter("euler_switch", euler_switch);
				this->get_parameter("magnetic_switch", magnetic_switch);
				this->get_parameter("temperature_switch", temperature_switch);
				this->get_parameter("pressure_switch", pressure_switch);
				this->get_parameter("publish_tf", publish_tf);
				this->get_parameter("tf_parent_frame", tf_parent_frame);
				this->get_parameter("tf_child_frame_id", tf_child_frame_id);
				if (tf_child_frame_id.empty()) {
					tf_child_frame_id = frame_id;
				}
				if (tf_child_frame_id.empty() || tf_child_frame_id.front() == '/' ||
					tf_child_frame_id.find_first_of(" \t\r\n\v\f") != std::string::npos) {
					throw std::invalid_argument("tf_child_frame_id must resolve to a nonempty frame name without a leading slash or whitespace");
				}
				if (publish_tf) {
					if (tf_parent_frame.empty() || tf_child_frame_id == tf_parent_frame ||
					    tf_parent_frame.front() == '/') {
						throw std::invalid_argument("TF frames must be nonempty, distinct, and have no leading slash");
					}
					tf_broadcaster = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
				}

				RCLCPP_INFO(this->get_logger(),"serial_port: %s\r\n", serial_port.c_str());
				RCLCPP_INFO(this->get_logger(), "baud_rate: %d\r\n", baud_rate);
				RCLCPP_INFO(this->get_logger(), "frame_id: %s\r\n", frame_id.c_str());
				RCLCPP_INFO(this->get_logger(), "imu_topic: %s\r\n", imu_topic.c_str());
				RCLCPP_INFO(this->get_logger(), "euler_topic: %s\r\n", euler_topic.c_str());
				RCLCPP_INFO(this->get_logger(), "magnetic_topic: %s\r\n", magnetic_topic.c_str());
				RCLCPP_INFO(this->get_logger(), "temperature_topic: %s\r\n", temperature_topic.c_str());
				RCLCPP_INFO(this->get_logger(), "pressure_topic: %s\r\n", pressure_topic.c_str());
				RCLCPP_INFO(this->get_logger(), "imu_switch: %d\r\n", imu_switch);
				RCLCPP_INFO(this->get_logger(), "euler_switch: %d\r\n", euler_switch);
				RCLCPP_INFO(this->get_logger(), "magnetic_switch: %d\r\n", magnetic_switch);
				RCLCPP_INFO(this->get_logger(), "temperature_switch: %d\r\n", temperature_switch);
				RCLCPP_INFO(this->get_logger(), "pressure_switch: %d\r\n", pressure_switch);
				RCLCPP_INFO(this->get_logger(), "publish_tf: %d\r\n", publish_tf);
				RCLCPP_INFO(this->get_logger(), "tf_parent_frame: %s\r\n", tf_parent_frame.c_str());
				RCLCPP_INFO(this->get_logger(), "tf_child_frame_id: %s\r\n", tf_child_frame_id.c_str());
                RCLCPP_INFO(this->get_logger(), "wait_for_device_timeout: %g", wait_for_device_timeout);
                RCLCPP_INFO(this->get_logger(), "reconnect_timeout: %g", reconnect_timeout);
                RCLCPP_INFO(this->get_logger(), "reconnect_attempts: %d", reconnect_attempts);
                RCLCPP_INFO(this->get_logger(), "data_timeout: %g", data_timeout);

                installation = this->declare_parameter<std::string>("installation", "");
                command_timeout_ms = this->declare_parameter<int>("command_timeout_ms", 2000);
                calibration_save = this->declare_parameter<bool>("calibration_save", false);
                command_verification = this->declare_parameter<bool>("command_verification", true);
                const auto session_valid_topic = declare_parameter<std::string>("session_valid_topic", "/imu_head_session_valid");
                const auto yaw_reset_applied_topic = declare_parameter<std::string>("yaw_reset_applied_topic", "/imu_head_yaw_reset_applied");
                if (session_valid_topic.empty() || yaw_reset_applied_topic.empty())
                    throw std::invalid_argument("State topic names must not be empty");
                if (command_timeout_ms < 100 || command_timeout_ms > 30000)
                    throw std::invalid_argument("command_timeout_ms must be 100..30000");
                validate_installation(installation);
                RCLCPP_INFO(this->get_logger(), "installation: %s", installation.c_str());
                if (!installation.empty() && (install_roll != 0.0 || install_pitch != 0.0 || install_yaw != 0.0)) {
                    RCLCPP_WARN(get_logger(),
                                "Device installation and software IMU attitude calibration are both enabled: "
                                "installation=[%s], software RPY (degrees)=[%g, %g, %g]. "
                                "These rotations are applied sequentially and may duplicate installation compensation; "
                                "check that both are intentional.",
                                installation.c_str(), install_roll, install_pitch, install_yaw);
                }
                RCLCPP_INFO(this->get_logger(), "command_timeout_ms: %d", command_timeout_ms);
                RCLCPP_INFO(this->get_logger(), "calibration_save: %d", calibration_save);
                RCLCPP_INFO(this->get_logger(), "command_verification: %d", command_verification);
				
				imu_pub = this->create_publisher<sensor_msgs::msg::Imu>(imu_topic, rclcpp::SensorDataQoS());
				euler_pub = this->create_publisher<geometry_msgs::msg::Vector3Stamped>(euler_topic, rclcpp::SensorDataQoS());
				magnetic_pub = this->create_publisher<sensor_msgs::msg::MagneticField>(magnetic_topic, rclcpp::SensorDataQoS());
				temp_pub = this->create_publisher<sensor_msgs::msg::Temperature>(temperature_topic, rclcpp::SensorDataQoS());
				pressure_pub = this->create_publisher<sensor_msgs::msg::FluidPressure>(pressure_topic, rclcpp::SensorDataQoS());

                configuration_ready.store(installation.empty());
                const auto state_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().transient_local();
                rclcpp::PublisherOptions state_options;
                // Humble intra-process publishers only support volatile durability.
                state_options.use_intra_process_comm = rclcpp::IntraProcessSetting::Disable;
                session_valid_pub = create_publisher<std_msgs::msg::Bool>(session_valid_topic, state_qos, state_options);
                yaw_reset_applied_pub = create_publisher<std_msgs::msg::Bool>(yaw_reset_applied_topic, state_qos, state_options);
                if (session_valid_pub->get_topic_name() == std::string(yaw_reset_applied_pub->get_topic_name()))
                    throw std::invalid_argument("State topics must resolve to distinct names");
                publish_session_state_locked();
                state_timer = create_wall_timer(1s, [this]() {
                    std::lock_guard<std::mutex> lock(command_mutex);
                    publish_session_state_locked();
                });
                install_in_progress.store(!installation.empty());
				running.store(true);
				reader_thread = std::thread([this]() {this->read_loop(); });
                if (!installation.empty()) {
                    bool port_open = false;
                    {
                        std::unique_lock<std::mutex> lock(command_mutex);
                        port_cv.wait(lock, [this] { return fd >= 0 || !running.load() || failed.load(); });
                        port_open = running.load() && !failed.load() && fd >= 0;
                    }
                    if (port_open)
                        configure_installation();
                    install_in_progress.store(false);
                }
                if (rclcpp::ok() && !failed.load())
                    register_services();
			}

			~IMUPublisher() override
			{
				running.store(false);
                command_cv.notify_all();
                port_cv.notify_all();

				if (reader_thread.joinable())
					reader_thread.join();

                std::lock_guard<std::mutex> lock(command_mutex);
				if (fd >= 0) {
					close(fd);
					fd = -1;
				}
			}

		private: 
            using SteadyClock = std::chrono::steady_clock;

            bool active() const { return rclcpp::ok() && running.load(); }

            // State is process-local, never persisted. Call with command_mutex held
            // (or during construction before starting the reader).
            void publish_session_state_locked()
            {
                std_msgs::msg::Bool msg;
                msg.data = session_valid;
                session_valid_pub->publish(msg);
                msg.data = yaw_reset_applied;
                yaw_reset_applied_pub->publish(msg);
            }

            void invalidate_session_locked()
            {
                ++session_generation;
                session_valid = false;
                yaw_reset_applied = false;
                publish_session_state_locked();
                command_cv.notify_all();
            }

            void fail(const char *reason)
            {
                RCLCPP_ERROR(get_logger(), "%s: %s; exiting node", serial_port.c_str(), reason);
                failed.store(true);
                running.store(false);
                command_cv.notify_all();
                port_cv.notify_all();
                rclcpp::shutdown();
            }

            void disconnect(const std::string &reason)
            {
                std::lock_guard<std::mutex> lock(command_mutex);
                RCLCPP_ERROR(get_logger(), "Serial device %s disconnected: %s",
                             serial_port.c_str(), reason.c_str());
                if (fd >= 0) close(fd);
                fd = -1;
                invalidate_session_locked();
                command_cv.notify_all();
            }

            SteadyClock::duration open_retry_delay() const
            {
                if (install_in_progress.load()) return std::chrono::milliseconds(200);
                return std::chrono::duration_cast<SteadyClock::duration>(std::chrono::duration<double>(reconnect_timeout));
            }

            SteadyClock::duration link_loss_delay() const
            {
                if (install_in_progress.load()) return SteadyClock::duration::zero();
                return open_retry_delay();
            }

            void configure_installation() {
                std::string detail;
                // Opening an already-streaming port can begin in the middle of a frame.
                // Establish decoder synchronization before mixing in a command response.
                const auto settle_until = std::chrono::steady_clock::now() + std::chrono::milliseconds(command_timeout_ms);
                while (running.load() && received_frames.load() < 5 &&
                       std::chrono::steady_clock::now() < settle_until)
                    std::this_thread::sleep_for(std::chrono::milliseconds(10));
                bool ok = !command_verification || query_installation(detail);
                if (ok && command_verification && installation_matches(detail)) {
                    RCLCPP_INFO(get_logger(), "Installation already matches; skipping write, save and reboot");
                } else if (ok) {
                    ok = command("CONFIG IMU URFR " + installation, detail) && command("SAVECONFIG", detail);
                    if (ok) {
                        // REBOOT need not reply. Drain its response before starting any transaction.
                        const std::string reboot = "REBOOT\r\n";
                        {
                            std::lock_guard<std::mutex> lock(command_mutex);
                            invalidate_session_locked(); // REBOOT may not disconnect USB.
                            ok = fd >= 0 && ::write(fd, reboot.data(), reboot.size()) == static_cast<ssize_t>(reboot.size());
                        }
                        if (ok) {
                            std::this_thread::sleep_for(std::chrono::seconds(3));
                            ok = !command_verification || query_installation(detail);
                            if (ok && command_verification && !installation_matches(detail)) {
                                ok = false;
                                detail = "Installation readback mismatch after reboot: " + detail;
                            }
                        }
                    }
                }
                configuration_ready.store(ok);
                if (!ok) RCLCPP_ERROR(get_logger(), "Installation could not be verified; publishing and calibration disabled: %s", detail.c_str());
                else RCLCPP_INFO(get_logger(), "%s", command_verification ? "Installation configuration verified" :
                    "Installation commands written; device execution and persistence NOT verified");
            }

            bool query_installation(std::string &detail) {
                for (int attempt = 1; attempt <= 3; ++attempt) {
                    // Only retry a completed read-only query. A timeout still locks the channel.
                    if (!command("LOG USRCONFIG", detail)) return false;
                    if (detail.find("\nURFR=") != std::string::npos) return true;
                    RCLCPP_WARN(get_logger(), "Incomplete LOG USRCONFIG response (%d/3): %s",
                                attempt, detail.c_str());
                    if (attempt < 3) std::this_thread::sleep_for(std::chrono::milliseconds(200));
                }
                detail = "LOG USRCONFIG repeatedly returned no URFR field; no installation write attempted: " + detail;
                return false;
            }

            bool installation_matches(const std::string &reply) const {
                const auto start = reply.find("URFR=");
                if (start == std::string::npos) return false;
                const auto end = reply.find_first_of("\r\n", start);
                std::string value = reply.substr(start + 5, end == std::string::npos ? end : end-start-5);
                value.erase(std::remove_if(value.begin(), value.end(), [](unsigned char c) { return std::isspace(c); }), value.end());
                if (installation.find(',') == std::string::npos) return value == installation || value == "0" + installation;
                std::replace(value.begin(), value.end(), ',', ' ');
                std::string requested = installation;
                std::replace(requested.begin(), requested.end(), ',', ' ');
                std::istringstream actual(value), expected(requested);
                double a, b;
                for (int i = 0; i < 9; ++i)
                    if (!(actual >> a) || !(expected >> b) || !std::isfinite(a) || std::abs(a-b)>1e-5) return false;
                actual >> std::ws;
                return actual.eof();
            }

            static void validate_installation(const std::string &value) {
                if (value.empty()) return;
                if (value.find(',') == std::string::npos) {
                    const std::string codes = " 24 35 43 52 125 134 142 153 205 214 240 251 304 315 341 350 402 413 421 430 503 512 520 531 ";
                    if (codes.find(" " + value + " ") == std::string::npos)
                        throw std::invalid_argument("installation must be a valid URFR code or rotation matrix");
                    return;
                }
                std::istringstream input(value);
                double m[9];
                for (int i = 0; i < 9; ++i) {
                    if (!(input >> m[i]) || !std::isfinite(m[i]))
                        throw std::invalid_argument("invalid installation matrix");
                    if (i < 8 && input.get() != ',')
                        throw std::invalid_argument("installation requires nine comma-separated numbers");
                }
                if (input.peek() != EOF) throw std::invalid_argument("invalid installation suffix");
                for (int i = 0; i < 3; ++i)
                    for (int j = 0; j < 3; ++j) {
                        double dot = 0;
                        for (int k = 0; k < 3; ++k) dot += m[i*3+k]*m[j*3+k];
                        if (std::abs(dot - (i == j ? 1.0 : 0.0)) > 0.001)
                            throw std::invalid_argument("installation matrix must be orthonormal");
                    }
                double det = m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6]);
                if (std::abs(det-1) > 0.001) throw std::invalid_argument("installation must be right-handed");
            }

            bool command(const std::string &text, std::string &detail, bool reset_yaw = false) {
                std::unique_lock<std::mutex> lock(command_mutex);
                if (command_fault || !running.load() || fd < 0) {
                    detail = (fd < 0 && running.load() && !command_fault)
                        ? "Serial port is disconnected"
                        : "Serial command channel unavailable; call reset_command_channel after checking device";
                    return false;
                }
                if (reset_yaw && !session_valid) {
                    detail = "Yaw reset rejected: no valid IMU data in the current session";
                    return false;
                }
                const auto generation = session_generation;
                if (reset_yaw) {
                    // A failed/unknown reset attempt must not retain an old true.
                    yaw_reset_applied = false;
                    publish_session_state_locked();
                }
                RCLCPP_INFO(get_logger(), "Serial TX: %s", text.c_str());
                const auto rx_start = received_bytes.load();
                const auto frames_start = received_frames.load();
                pending = true;
                ascii_line.clear();
                response.clear();
                query_lines.clear();
                const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(command_timeout_ms);
                const std::string wire = text + "\r\n";
                size_t offset = 0;
                while (offset < wire.size() && std::chrono::steady_clock::now() < deadline) {
                    const auto n = ::write(fd, wire.data()+offset, wire.size()-offset);
                    if (n > 0) offset += static_cast<size_t>(n);
                    else if (n < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) break;
                    else { struct pollfd out{fd, POLLOUT, 0}; ::poll(&out, 1, 10); }
                }
                if (offset == wire.size() && !command_verification && text.compare(0, 4, "LOG ") != 0) {
                    pending = false;
                    detail = "Command [" + text + "] written; device execution NOT verified";
                    lock.unlock();
                    // Space consecutive writes while the reader discards unsolicited replies.
                    std::this_thread::sleep_for(std::chrono::milliseconds(200));
                    return true;
                }
                const bool got_reply = offset == wire.size() &&
                    command_cv.wait_until(lock, deadline, [this, generation] {
                        return !response.empty() || !running.load() || fd < 0 || session_generation != generation;
                    });
                pending = false;
                if (!got_reply || !running.load() || fd < 0 || session_generation != generation || response.empty()) {
                    command_fault = true; // An untagged late OK must never acknowledge a later command.
                    detail = "Command [" + text + "] timed out; written=" + std::to_string(offset) +
                        "/" + std::to_string(wire.size()) + ", received_bytes=" +
                        std::to_string(received_bytes.load()-rx_start) + ", valid_frames=" +
                        std::to_string(received_frames.load()-frames_start) +
                        ", ASCII=[" + query_lines + "], partial=[" + ascii_line +
                        "]. Device state unknown; call reset_command_channel or restart node before further commands";
                    if (fd < 0) detail += " Serial port disconnected during the command.";
                    RCLCPP_ERROR(get_logger(), "%s", detail.c_str());
                    return false;
                }
                if (reset_yaw && response == "OK" && session_valid) {
                    yaw_reset_applied = true;
                    publish_session_state_locked();
                }
                detail = "Command [" + text + "]: " + response + query_lines;
                RCLCPP_INFO(get_logger(), "Serial RX: %s", detail.c_str());
                return response == "OK";
            }

            void ascii_byte(uint8_t byte) {
                std::lock_guard<std::mutex> lock(command_mutex);
                last_ascii_received = std::chrono::steady_clock::now();
                if (byte == '\r' || byte == '\n') {
                    const auto first = ascii_line.find_first_not_of(" \t");
                    const auto last = ascii_line.find_last_not_of(" \t");
                    const std::string line = first == std::string::npos ? "" :
                        ascii_line.substr(first, last-first+1);
                    if (pending && !line.empty()) {
                        const auto error_token = [&line](const std::string &prefix) {
                            return line == prefix || (line.compare(0, prefix.size(), prefix) == 0 &&
                                (line[prefix.size()] == ':' || line[prefix.size()] == ' '));
                        };
                        if (line == "OK" || error_token("ERR") || error_token("ERROR")) {
                            if (response.empty()) response = line;
                            command_cv.notify_all();
                        } else if (query_lines.size() < 4096) query_lines += "\n" + line;
                    }
                    ascii_line.clear();
                } else if ((byte >= 32 && byte <= 126) || byte == '\t') {
                    if (ascii_line.size() < 512) ascii_line += static_cast<char>(byte);
                    else ascii_line.clear();
                } else ascii_line.clear();
            }

            void add_service(const std::string &name, const std::string &request, bool save_after_success, bool require_configuration = true, bool reset_yaw = false) {
                services.push_back(create_service<std_srvs::srv::Trigger>(name,
                    [this, request, save_after_success, require_configuration, reset_yaw](const std::shared_ptr<std_srvs::srv::Trigger::Request>,
                                         std::shared_ptr<std_srvs::srv::Trigger::Response> result) {
                        if (require_configuration && !configuration_ready.load()) {
                            result->message = "Installation not verified; check configuration and restart node";
                            return;
                        }
                        result->success = command(request, result->message, reset_yaw);
                        if (result->success && save_after_success) {
                            std::string detail;
                            result->success = command("SAVECONFIG", detail);
                            result->message = result->success ? (command_verification ? "Calibration acknowledged and saved" : "Calibration and save commands written; device execution NOT verified") : "Calibration applied but save failed: " + detail;
                        }
                    }));
            }

            void register_services() {
                services.push_back(create_service<std_srvs::srv::Trigger>("~/reset_command_channel",
                    [this](const std::shared_ptr<std_srvs::srv::Trigger::Request>,
                           std::shared_ptr<std_srvs::srv::Trigger::Response> result) {
                        std::unique_lock<std::mutex> lock(command_mutex);
                        if (!running.load() || fd < 0 || pending) {
                            result->message = "Serial reader unavailable or command in progress";
                            return;
                        }
                        if (!command_fault) {
                            result->success = true;
                            result->message = "Command channel is already unlocked";
                            return;
                        }
                        const auto quiet = std::chrono::milliseconds(command_timeout_ms);
                        const auto started = std::chrono::steady_clock::now();
                        const auto deadline = started + 3 * quiet;
                        // Reader continues consuming data; pending=false discards unsolicited replies.
                        for (;;) {
                            const auto now = std::chrono::steady_clock::now();
                            const auto quiet_until = std::max(started, last_ascii_received) + quiet;
                            if (!running.load()) {
                                result->message = "Serial reader stopped; channel remains locked";
                                return;
                            }
                            if (now >= quiet_until) break;
                            if (now >= deadline) {
                                result->message = "ASCII input did not settle; channel remains locked";
                                return;
                            }
                            command_cv.wait_until(lock, std::min(quiet_until, deadline));
                        }
                        response.clear();
                        query_lines.clear();
                        ascii_line.clear();
                        command_fault = false;
                        result->success = true;
                        result->message = "Software command lock cleared; previous command outcome is still unknown";
                    }));
                add_service("~/get_version", "LOG VERSION", false, false);
                add_service("~/get_configuration", "LOG USRCONFIG", false, false);
                add_service("~/reset_yaw", "CONFIG ATT RST 1", false, true, true);
                add_service("~/calibrate_level", "CONFIG ATT RST 2", calibration_save);
                add_service("~/auto_level", "CONFIG ATT RST 3", calibration_save);
                add_service("~/clear_level", "CONFIG ATT RST 5", calibration_save);
                add_service("~/save_config", "SAVECONFIG", false);
            }

            void read_loop()
            {
                const auto startup = SteadyClock::now();
                auto next_attempt = startup;
                auto last_frame = startup;
                bool ever_connected = false;
                bool confirmed = false;
                int attempts = 0;
                while (active()) {
                    const auto now = SteadyClock::now();
                    if (!ever_connected && wait_for_device_timeout >= 0 &&
                        std::chrono::duration<double>(now - startup).count() >= wait_for_device_timeout) {
                        fail("wait_for_device_timeout expired before receiving valid IMU data");
                        break;
                    }
                    if (fd < 0) {
                        if (ever_connected && reconnect_attempts >= 0 && attempts >= reconnect_attempts) {
                            fail("reconnect_attempts exhausted");
                            break;
                        }
                        if (now < next_attempt) {
                            std::this_thread::sleep_for(20ms);
                            continue;
                        }
                        if (ever_connected) {
                            if (reconnect_attempts >= 0) ++attempts;
                            RCLCPP_INFO(get_logger(), "Reconnecting to configured serial port %s (attempt %d, limit %d)",
                                        serial_port.c_str(), attempts, reconnect_attempts);
                        }
                        const int opened = open_ttyport(serial_port, baud_rate);
                        next_attempt = SteadyClock::now() + open_retry_delay();
                        if (opened < 0) continue;
                        if (!active()) {
                            close(opened);
                            break;
                        }
                        {
                            std::lock_guard<std::mutex> lock(command_mutex);
                            fd = opened;
                            invalidate_session_locked();
                            raw = {};
                            ascii_sync_pending = false;
                            ascii_line.clear();
                            if (!pending) {
                                received_bytes.store(0);
                                received_frames.store(0);
                            }
                            port_cv.notify_all();
                        }
                        imu_msg = decltype(imu_msg)();
                        magnetic_msg = decltype(magnetic_msg)();
                        euler_msg = decltype(euler_msg)();
                        temp_msg = decltype(temp_msg)();
                        pre_msg = decltype(pre_msg)();
                        confirmed = false;
                        last_frame = SteadyClock::now();
                    }

                    if (!install_in_progress.load() &&
                        std::chrono::duration<double>(SteadyClock::now() - last_frame).count() >= data_timeout) {
                        disconnect("no valid IMU data within data_timeout");
                        next_attempt = SteadyClock::now() + link_loss_delay();
                        continue;
                    }
                    struct pollfd p{};
                    p.fd = fd;
                    p.events = POLLIN;
                    int rpoll = poll(&p, 1, 20);
                    std::string error;
                    if (rpoll < 0 && errno != EINTR) error = std::strerror(errno);
                    if (rpoll > 0 && (p.revents & (POLLERR | POLLHUP | POLLNVAL)))
                        error = "poll reported hangup/error (device unplugged)";
                    if (!error.empty()) {
                        disconnect(error);
                        next_attempt = SteadyClock::now() + link_loss_delay();
                        continue;
                    }
                    if (rpoll <= 0 || !(p.revents & POLLIN)) continue;
                    int n = read(fd, buf, sizeof(buf));
                    if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
                    if (n <= 0) {
                        disconnect(n == 0 ? "end of serial stream" : std::strerror(errno));
                        next_attempt = SteadyClock::now() + link_loss_delay();
                        continue;
                    }

					for (int i = 0; i < n; i++) {
						const bool binary = raw.nbyte != 0;
						int rev = hipnuc_input(&raw, buf[i]);
                        ++received_bytes;
                        if (!binary) {
                            if (raw.nbyte != 0) {
                                ascii_sync_pending = false; // 5A A5 starts a binary frame.
                            } else {
                                // Hold 5A until the next byte distinguishes a header from ASCII Z.
                                if (ascii_sync_pending) ascii_byte(0x5a);
                                ascii_sync_pending = buf[i] == 0x5a;
                                if (!ascii_sync_pending) ascii_byte(buf[i]);
                            }
                        }
                        if (rev > 0) ++received_frames;
						if (rev <= 0) continue;

                        if (raw.hi83.tag == 0x83)
                        {
                            uint32_t bm = raw.hi83.data_bitmap;

                            if (bm & HI83_BMAP_QUAT)
                            {
                                imu_msg.orientation.w = raw.hi83.quat[0];
                                imu_msg.orientation.x = raw.hi83.quat[1];
                                imu_msg.orientation.y = raw.hi83.quat[2];
                                imu_msg.orientation.z = raw.hi83.quat[3];
                            }
                            if (bm & HI83_BMAP_GYR_B)
                            {
                                imu_msg.angular_velocity.x = raw.hi83.gyr_b[0];
                                imu_msg.angular_velocity.y = raw.hi83.gyr_b[1];
                                imu_msg.angular_velocity.z = raw.hi83.gyr_b[2];
                            }
                            if (bm & HI83_BMAP_ACC_B)
                            {
                                imu_msg.linear_acceleration.x = raw.hi83.acc_b[0];
                                imu_msg.linear_acceleration.y = raw.hi83.acc_b[1];
                                imu_msg.linear_acceleration.z = raw.hi83.acc_b[2];
                            }
							if (bm & HI83_BMAP_MAG_B)
							{
								magnetic_msg.magnetic_field.x = raw.hi83.mag_b[0] * UTESLA_TO_TESLA ;
								magnetic_msg.magnetic_field.y = raw.hi83.mag_b[1] * UTESLA_TO_TESLA ;
								magnetic_msg.magnetic_field.z = raw.hi83.mag_b[2] * UTESLA_TO_TESLA ;
							}

							if (bm & HI83_BMAP_RPY)
							{
								euler_msg.vector.x = raw.hi83.rpy[0] * DEG_TO_RAD;
								euler_msg.vector.y = raw.hi83.rpy[1] * DEG_TO_RAD;
								euler_msg.vector.z = raw.hi83.rpy[2] * DEG_TO_RAD;
							}

							if (bm & HI83_BMAP_AIR_PRESSURE)
							{
								pre_msg.fluid_pressure = raw.hi83.air_pressure;
							}

							if (bm & HI83_BMAP_TEMPERATURE)
							{
								temp_msg.temperature = raw.hi83.temperature;
							}

							if (!(raw.hi83.main_status & (1 << 11)) && (bm & HI83_BMAP_UTC))
							{
								imu_msg.header.stamp.sec = utc_to_unix(2000 + raw.hi83.utc.year, raw.hi83.utc.month, raw.hi83.utc.day, raw.hi83.utc.hour, raw.hi83.utc.min, raw.hi83.utc.sec_ms / 1000 % 60);
								imu_msg.header.stamp.nanosec = raw.hi83.utc.sec_ms % 1000 * 1000000;

								magnetic_msg.header.stamp.sec = utc_to_unix(2000 + raw.hi83.utc.year, raw.hi83.utc.month, raw.hi83.utc.day, raw.hi83.utc.hour, raw.hi83.utc.min, raw.hi83.utc.sec_ms / 1000 % 60);
								magnetic_msg.header.stamp.nanosec = raw.hi83.utc.sec_ms % 1000 * 1000000;

								euler_msg.header.stamp.sec = utc_to_unix(2000 + raw.hi83.utc.year, raw.hi83.utc.month, raw.hi83.utc.day, raw.hi83.utc.hour, raw.hi83.utc.min, raw.hi83.utc.sec_ms / 1000 % 60);
								euler_msg.header.stamp.nanosec = raw.hi83.utc.sec_ms % 1000 * 1000000;

								temp_msg.header.stamp.sec = utc_to_unix(2000 + raw.hi83.utc.year, raw.hi83.utc.month, raw.hi83.utc.day, raw.hi83.utc.hour, raw.hi83.utc.min, raw.hi83.utc.sec_ms / 1000 % 60);
								temp_msg.header.stamp.nanosec = raw.hi83.utc.sec_ms % 1000 * 1000000;

								pre_msg.header.stamp.sec = utc_to_unix(2000 + raw.hi83.utc.year, raw.hi83.utc.month, raw.hi83.utc.day, raw.hi83.utc.hour, raw.hi83.utc.min, raw.hi83.utc.sec_ms / 1000 % 60);
								pre_msg.header.stamp.nanosec = raw.hi83.utc.sec_ms % 1000 * 1000000;

							}
							else
							{
								imu_msg.header.stamp = rclcpp::Clock().now();
								magnetic_msg.header.stamp = rclcpp::Clock().now();
								euler_msg.header.stamp = rclcpp::Clock().now();
								temp_msg.header.stamp = rclcpp::Clock().now();
								pre_msg.header.stamp = rclcpp::Clock().now();
							}
                        }
                        else if (raw.hi91.tag == 0x91)
                        {
                            imu_msg.orientation.w = raw.hi91.quat[0];
                            imu_msg.orientation.x = raw.hi91.quat[1]; 
                            imu_msg.orientation.y = raw.hi91.quat[2];
                            imu_msg.orientation.z = raw.hi91.quat[3];
                            imu_msg.angular_velocity.x = raw.hi91.gyr[0] * DEG_TO_RAD;
                            imu_msg.angular_velocity.y = raw.hi91.gyr[1] * DEG_TO_RAD;
                            imu_msg.angular_velocity.z = raw.hi91.gyr[2] * DEG_TO_RAD;
                            imu_msg.linear_acceleration.x = raw.hi91.acc[0] * GRA_ACC;
                            imu_msg.linear_acceleration.y = raw.hi91.acc[1] * GRA_ACC;
                            imu_msg.linear_acceleration.z = raw.hi91.acc[2] * GRA_ACC;

							euler_msg.vector.x = raw.hi91.roll  * DEG_TO_RAD;
							euler_msg.vector.y = raw.hi91.pitch * DEG_TO_RAD;
							euler_msg.vector.z = raw.hi91.yaw   * DEG_TO_RAD;

							magnetic_msg.magnetic_field.x = raw.hi91.mag[0] * UTESLA_TO_TESLA ;
							magnetic_msg.magnetic_field.y = raw.hi91.mag[1] * UTESLA_TO_TESLA ;
							magnetic_msg.magnetic_field.z = raw.hi91.mag[2] * UTESLA_TO_TESLA ;

							temp_msg.temperature = raw.hi91.temp;

							pre_msg.fluid_pressure = raw.hi91.air_pressure;

							imu_msg.header.stamp = rclcpp::Clock().now();
							magnetic_msg.header.stamp = rclcpp::Clock().now();
							euler_msg.header.stamp = rclcpp::Clock().now();
							temp_msg.header.stamp = rclcpp::Clock().now();
							pre_msg.header.stamp = rclcpp::Clock().now();
                        }
						else 
							continue;

                        last_frame = SteadyClock::now();
                        {
                            std::lock_guard<std::mutex> lock(command_mutex);
                            if (!session_valid && fd >= 0) {
                                session_valid = true;
                                publish_session_state_locked();
                            }
                        }
                        if (!confirmed) {
                            RCLCPP_INFO(get_logger(), "Connected to %s: valid IMU data received; retry count reset",
                                        serial_port.c_str());
                            confirmed = true;
                            ever_connected = true;
                            attempts = 0;
                        }
                        if (!configuration_ready.load()) continue;

                        // Keep the cached decoder messages in sensor coordinates. HI83 may
                        // omit fields; rotating that cache would apply calibration repeatedly.
                        auto imu_msg = this->imu_msg;
                        auto magnetic_msg = this->magnetic_msg;
                        auto euler_msg = this->euler_msg;
                        installation_rotation.apply(imu_msg, magnetic_msg, euler_msg);

                        if (tf_broadcaster) {
                            geometry_msgs::msg::TransformStamped transform;
                            transform.header.stamp = imu_msg.header.stamp;
                            transform.header.frame_id = tf_parent_frame;
                            transform.child_frame_id = tf_child_frame_id;
                            // IMU provides orientation only; translation remains zero.
                            auto q = imu_msg.orientation;
                            const double norm = std::sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w);
                            if (std::isfinite(norm) && norm > 1e-6) {
                                q.x /= norm;
                                q.y /= norm;
                                q.z /= norm;
                                q.w /= norm;
                                transform.transform.rotation = q;
                                tf_broadcaster->sendTransform(transform);
                            } else {
                                RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
                                                     "Skipping TF: invalid IMU quaternion");
                            }
                        }

						if (imu_switch) {
							imu_msg.header.frame_id = frame_id;
							imu_pub->publish(imu_msg);
						}
                       
						if (magnetic_switch) {
							magnetic_msg.header.frame_id = frame_id;
							magnetic_pub->publish(magnetic_msg);
						}
						
						if (euler_switch) {
							euler_msg.header.frame_id = frame_id;
							euler_pub->publish(euler_msg);
						}

						if (temperature_switch) {
							temp_msg.header.frame_id = frame_id;
							temp_pub->publish(temp_msg);
						}

						if (pressure_switch) {
							pre_msg.header.frame_id = frame_id;
							pressure_pub->publish(pre_msg);
						}	
					}
				}
			}

			int open_ttyport(const std::string &tty_port, int baud)
			{
				const char *port_device = tty_port.c_str();
				int serial_port = open(port_device, O_RDWR | O_NOCTTY | O_NONBLOCK);
				if (serial_port < 0)
				{
					RCLCPP_ERROR(this->get_logger(), "Error opening serial port %s: %s", port_device, std::strerror(errno));
					return -1;
				}

				struct termios2 tty {};

				if (ioctl(serial_port, TCGETS2, &tty) != 0)
				{
					RCLCPP_ERROR(this->get_logger(), "TCGETS2 failed: %s ", std::strerror(errno));
					close(serial_port);
					return -1;
				}

				tty.c_cflag &= ~CBAUD;
				tty.c_cflag |= BOTHER;

				tty.c_ispeed = baud;
				tty.c_ospeed = baud;

				tty.c_cflag &= ~CSIZE;
				tty.c_cflag |= CS8 | CLOCAL | CREAD;
				tty.c_oflag &= ~OPOST; // Preserve command CRLF exactly.
				tty.c_cflag &= ~PARENB;
				tty.c_cflag &= ~CSTOPB;
				tty.c_cflag &= ~CRTSCTS;

				tty.c_lflag &= ~ICANON;
				tty.c_lflag &= ~ECHO;
				tty.c_lflag &= ~ECHOE;
				tty.c_lflag &= ~ECHONL;
				tty.c_lflag &= ~ISIG;

				tty.c_iflag &= ~(IXON | IXOFF | IXANY);
				tty.c_iflag &= ~(IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL);

				tty.c_cc[VTIME] = 10;
				tty.c_cc[VMIN] = 0;

				if (ioctl(serial_port, TCSETS2, &tty) != 0)
				{
					RCLCPP_ERROR(this->get_logger(), "TCSETS2 failed : %s", std::strerror(errno));
					close(serial_port);
					return -1;
				}

				return serial_port;
			}

			time_t utc_to_unix(int year, int month, int day, int hour, int minute, int second) 
			{
				struct tm tm_time;
				time_t timestamp;

				tm_time.tm_year = year - 1900;
				tm_time.tm_mon = month - 1;
				tm_time.tm_mday = day;
				tm_time.tm_hour = hour;
				tm_time.tm_min = minute;
				tm_time.tm_sec = second;
				tm_time.tm_isdst = 0;  
				

				#ifdef _WIN32
				timestamp = _mkgmtime(&tm_time);  
				#else
				timestamp = timegm(&tm_time);
				#endif
				
				return timestamp;
			}

			int fd = -1;
            InstallationRotation installation_rotation;
            std::atomic<uint64_t> received_bytes{0}, received_frames{0};
            bool ascii_sync_pending = false;
            hipnuc_raw_t raw{};
            std::string installation;
            int command_timeout_ms = 2000;
            bool calibration_save = false;
            bool command_verification = true;
            std::atomic<bool> configuration_ready{true};
            std::atomic<bool> install_in_progress{false};
            std::mutex command_mutex;
            std::condition_variable command_cv;
            std::condition_variable port_cv;
            bool pending = false;
            bool command_fault = false;
            std::chrono::steady_clock::time_point last_ascii_received{};
            std::string response, query_lines, ascii_line;
            std::vector<rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr> services;
            // All session fields and publication ordering are protected by command_mutex.
            bool session_valid = false;
            bool yaw_reset_applied = false;
            uint64_t session_generation = 0;
            rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr session_valid_pub;
            rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr yaw_reset_applied_pub;
            rclcpp::TimerBase::SharedPtr state_timer;
            double wait_for_device_timeout;
            double reconnect_timeout;
            double data_timeout;
            int reconnect_attempts;
            std::atomic<bool> failed{false};
        public:
            bool has_failed() const { return failed.load(); }
        private:
			uint8_t buf[BUF_SIZE] = {0};

			std::string serial_port;
			int baud_rate;
			std::string frame_id;
			bool imu_switch;
			bool euler_switch;
			bool magnetic_switch;
			bool temperature_switch;
			bool pressure_switch;
			std::string imu_topic;
			std::string euler_topic;
			std::string magnetic_topic;
			std::string temperature_topic;
			std::string pressure_topic;
			bool publish_tf;
			std::string tf_parent_frame;
			std::string tf_child_frame_id;
			std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster;

			sensor_msgs::msg::Imu imu_msg;
			sensor_msgs::msg::MagneticField magnetic_msg;
			geometry_msgs::msg::Vector3Stamped euler_msg;
			sensor_msgs::msg::Temperature temp_msg;
			sensor_msgs::msg::FluidPressure pre_msg;

			rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_pub;
			rclcpp::Publisher<sensor_msgs::msg::MagneticField>::SharedPtr magnetic_pub;
			rclcpp::Publisher<geometry_msgs::msg::Vector3Stamped>::SharedPtr euler_pub;
			rclcpp::Publisher<sensor_msgs::msg::Temperature>::SharedPtr temp_pub;
			rclcpp::Publisher<sensor_msgs::msg::FluidPressure>::SharedPtr pressure_pub;
			
			std::atomic<bool> running{false};
			std::thread reader_thread;
	};
}


int main(int argc, const char * argv[])
{
	rclcpp::init(argc, argv);
	rclcpp::NodeOptions options;
	options.use_intra_process_comms(true);
	auto node = std::make_shared<hipnuc_driver::IMUPublisher>(options);
    rclcpp::spin(node);
    const bool failed = node->has_failed();
    if (rclcpp::ok()) rclcpp::shutdown();
    return failed ? 1 : 0;
}

#include "rclcpp_components/register_node_macro.hpp"
RCLCPP_COMPONENTS_REGISTER_NODE(hipnuc_driver::IMUPublisher)
