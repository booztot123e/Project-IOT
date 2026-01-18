# sensor/max6675_reader.py
import time
import spidev

class Max6675:
    """
    MAX6675 over SPI
    Pi5 SPI0: bus=0
    device=0 => CE0 (/dev/spidev0.0)
    device=1 => CE1 (/dev/spidev0.1)
    """
    def __init__(self, bus=0, device=0, max_speed_hz=500000):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = max_speed_hz
        self.spi.mode = 0b00

    def read_c(self) -> float:
        # อ่าน 2 bytes
        raw = self.spi.readbytes(2)
        value = (raw[0] << 8) | raw[1]

        # bit2 = 1 แปลว่า thermocouple open
        if value & 0x4:
            raise RuntimeError("MAX6675: Thermocouple open / not connected")

        # อุณหภูมิอยู่บิต 14..3 (shift 3)
        temp_c = (value >> 3) * 0.25
        return temp_c

    def close(self):
        try:
            self.spi.close()
        except:
            pass

if __name__ == "__main__":
    s = Max6675(bus=0, device=0)  # ถ้าใช้ CE0
    try:
        while True:
            t = s.read_c()
            print(f"Temp: {t:.2f} °C")
            time.sleep(1)
    finally:
        s.close()
