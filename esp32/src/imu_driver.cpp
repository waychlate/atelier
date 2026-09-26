#include "imu_driver.h"

#include <Wire.h>

#include "config.h"

namespace {

constexpr uint8_t REG_CONFIG        = 0x1A;
constexpr uint8_t REG_GYRO_CONFIG   = 0x1B;
constexpr uint8_t REG_ACCEL_CONFIG  = 0x1C;
constexpr uint8_t REG_ACCEL_CONFIG2 = 0x1D;
constexpr uint8_t REG_ACCEL_XOUT_H  = 0x3B;
constexpr uint8_t REG_PWR_MGMT_1    = 0x6B;
constexpr uint8_t REG_WHO_AM_I      = 0x75;

constexpr float GRAVITY       = 9.80665f;
constexpr float ACCEL_LSB_PER_G   = 8192.0f;  // ±4 g
constexpr float GYRO_LSB_PER_DPS  = 32.8f;    // ±1000 dps

bool write_reg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MPU9250_I2C_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

bool read_regs(uint8_t reg, uint8_t *buf, size_t len) {
    Wire.beginTransmission(MPU9250_I2C_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((uint8_t)MPU9250_I2C_ADDR, (uint8_t)len) != len) return false;
    for (size_t i = 0; i < len; i++) buf[i] = Wire.read();
    return true;
}

// Lists every address that ACKs, to tell wiring faults from address mismatches.
void scan_i2c_bus() {
    Serial.print("[IMU] I2C scan:");
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf(" 0x%02X", addr);
            found++;
        }
    }
    Serial.println(found ? "" : " no devices found");
}

inline int16_t be16(const uint8_t *p) {
    return (int16_t)((p[0] << 8) | p[1]);
}

}  // namespace

bool imu_init() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    Wire.setClock(I2C_CLOCK_HZ);

    // Wake from sleep and select the PLL gyro clock (more stable than internal RC).
    if (!write_reg(REG_PWR_MGMT_1, 0x01)) {
        Serial.println("[IMU] No ACK from MPU-9250 - check wiring/address");
        scan_i2c_bus();
        return false;
    }
    delay(100);

    uint8_t who = 0;
    read_regs(REG_WHO_AM_I, &who, 1);
    Serial.printf("[IMU] WHO_AM_I = 0x%02X%s\n", who,
                  who == 0x71 ? " (MPU-9250)" : " (unexpected, continuing)");

    bool ok = true;
    ok &= write_reg(REG_CONFIG, 0x03);         // gyro DLPF ~41 Hz
    ok &= write_reg(REG_GYRO_CONFIG, 0x10);    // FS_SEL=2  -> ±1000 dps
    ok &= write_reg(REG_ACCEL_CONFIG, 0x08);   // AFS_SEL=1 -> ±4 g
    ok &= write_reg(REG_ACCEL_CONFIG2, 0x03);  // accel DLPF ~41 Hz
    if (!ok) {
        Serial.println("[IMU] Failed to write configuration registers");
        return false;
    }

    Serial.println("[IMU] Initialized (±4 g, ±1000 dps)");
    return true;
}

bool imu_read(ImuSample &out) {
    uint8_t buf[14];
    if (!read_regs(REG_ACCEL_XOUT_H, buf, sizeof(buf))) return false;

    // Layout: AX AY AZ TEMP GX GY GZ, each big-endian int16.
    out.ax = be16(&buf[0])  / ACCEL_LSB_PER_G * GRAVITY;
    out.ay = be16(&buf[2])  / ACCEL_LSB_PER_G * GRAVITY;
    out.az = be16(&buf[4])  / ACCEL_LSB_PER_G * GRAVITY;
    out.gx = be16(&buf[8])  / GYRO_LSB_PER_DPS;
    out.gy = be16(&buf[10]) / GYRO_LSB_PER_DPS;
    out.gz = be16(&buf[12]) / GYRO_LSB_PER_DPS;
    return true;
}
