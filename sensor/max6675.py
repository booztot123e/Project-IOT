import time, spidev, statistics

CONV_TIME = 0.25  # ~220ms ต่อการแปลง 1 ค่า
_reader = None

class Max6675:
    def __init__(self, bus=0, ce=0, hz=4_000_000, samples=3):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, ce)
        self.spi.max_speed_hz = hz
        self.spi.mode = 0
        self.samples = samples

    def read_c(self) -> float:
        vals = []
        for _ in range(self.samples):
            h, l = self.spi.xfer2([0, 0])
            v = (h << 8) | l
            if v & 0x04:
                raise RuntimeError("Thermocouple not connected")
            vals.append((v >> 3) * 0.25)   # 12-bit, step 0.25°C
            time.sleep(CONV_TIME)
        return statistics.median(vals)

def get_reader():
    global _reader
    if _reader is None:
        _reader = Max6675(bus=0, ce=0)   # ใช้ CE1 → เปลี่ยนเป็น ce=1
    return _reader

def get_temp_c() -> float:
    return get_reader().read_c()
