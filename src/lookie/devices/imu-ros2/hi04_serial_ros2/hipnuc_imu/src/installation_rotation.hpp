#pragma once

#include <cmath>
#include <stdexcept>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2/LinearMath/Quaternion.h>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/magnetic_field.hpp>
#include <geometry_msgs/msg/vector3_stamped.hpp>

namespace hipnuc_driver
{
// Positive calibration rotates the output attitude about the sensor-local axes.
class InstallationRotation
{
public:
    InstallationRotation(double roll = 0, double pitch = 0, double yaw = 0)
        : enabled_(roll != 0 || pitch != 0 || yaw != 0)
    {
        if (!std::isfinite(roll) || !std::isfinite(pitch) || !std::isfinite(yaw)) {
            throw std::invalid_argument("IMU calibration RPY must be finite degrees");
        }
        constexpr double radians = 3.14159265358979323846 / 180.0;
        rotation_.setRPY(std::remainder(roll, 360.0) * radians,
                         std::remainder(pitch, 360.0) * radians,
                         std::remainder(yaw, 360.0) * radians);
    }
    
    void apply(sensor_msgs::msg::Imu &imu,
               sensor_msgs::msg::MagneticField &mag,
               geometry_msgs::msg::Vector3Stamped &euler) const
    {
        if (!enabled_) return;
        auto &q = imu.orientation;
        tf2::Quaternion attitude(q.x, q.y, q.z, q.w);
        if (std::isfinite(attitude.length2()) && attitude.length2() > 1e-12) {
            // R_world_output = R_world_sensor * R_sensor_output.
            attitude = attitude.normalized() * rotation_;
            q.x = attitude.x(); q.y = attitude.y();
            q.z = attitude.z(); q.w = attitude.w();
        }
        rotate(imu.angular_velocity);
        rotate(imu.linear_acceleration);
        rotate(mag.magnetic_field);
        // The Euler field is independently available in HI83 packets.
        tf2::Quaternion euler_attitude;
        euler_attitude.setRPY(euler.vector.x, euler.vector.y, euler.vector.z);
        tf2::Matrix3x3(euler_attitude * rotation_).getRPY(
            euler.vector.x, euler.vector.y, euler.vector.z);
        // The driver leaves covariance arrays zero (unknown).
    }

private:
    void rotate(geometry_msgs::msg::Vector3 &v) const
    {
        // Vector coordinates transform inversely to the output frame attitude.
        const auto result = tf2::quatRotate(rotation_.inverse(), tf2::Vector3(v.x, v.y, v.z));
        v.x = result.x(); v.y = result.y(); v.z = result.z();
    }
    bool enabled_;
    tf2::Quaternion rotation_;
};
}  // namespace hipnuc_driver
