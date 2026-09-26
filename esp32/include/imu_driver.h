#pragma once

#include <Arduino.h>

struct ImuSample {
    uint32_t t;             // ms since stroke start
    float ax, ay, az;       // m/s^2
    float gx, gy, gz;       // deg/s
};

// Wakes the MPU-9250 and configures ±4 g / ±1000 dps. Returns false if the
// device does not respond on the I2C bus.
bool imu_init();

// Burst-reads accel + temp + gyro (14 bytes from 0x3B) and converts to
// engineering units. Leaves `t` untouched. Returns false on I2C error.
bool imu_read(ImuSample &out);
