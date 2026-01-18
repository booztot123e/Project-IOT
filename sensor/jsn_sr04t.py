# sensor/jsn_sr04t.py
import time
from statistics import median
import lgpio

class JSNSR04T:
    """
    JSN-SR04T (waterproof ultrasonic) on Raspberry Pi using lgpio.
    TRIG: GPIO output (3.3V OK)
    ECHO: GPIO input (MUST go through voltage divider to 3.3V)
    """
    def __init__(self, trig=23, echo=24, chip=0, warmup=5):
        self.trig = int(trig)
        self.echo = int(echo)
        self.h = lgpio.gpiochip_open(int(chip))

        lgpio.gpio_claim_output(self.h, self.trig, 0)
        lgpio.gpio_claim_input(self.h, self.echo)

        # warmup (sensor sometimes needs a few pulses)
        for _ in range(int(warmup)):
            self.read_distance_cm()
            time.sleep(0.05)

    def close(self):
        try:
            lgpio.gpiochip_close(self.h)
        except Exception:
            pass

    def read_distance_cm(self, timeout=0.06):
        """
        Return distance in cm (float) or None on timeout.
        """
        # trigger 10us
        lgpio.gpio_write(self.h, self.trig, 0)
        time.sleep(0.000005)
        lgpio.gpio_write(self.h, self.trig, 1)
        time.sleep(0.00001)
        lgpio.gpio_write(self.h, self.trig, 0)

        t0 = time.monotonic()
        while lgpio.gpio_read(self.h, self.echo) == 0:
            if time.monotonic() - t0 > timeout:
                return None

        start = time.monotonic()
        while lgpio.gpio_read(self.h, self.echo) == 1:
            if time.monotonic() - start > timeout:
                return None

        end = time.monotonic()
        pulse = end - start
        return (pulse * 34300) / 2.0

    def read_filtered_cm(self, samples=7, min_cm=5.0, max_cm=200.0):
        """
        Median filter. Return cm or None if not enough good samples.
        """
        vals = []
        for _ in range(int(samples)):
            d = self.read_distance_cm()
            if d is not None and min_cm <= d <= max_cm:
                vals.append(d)
            time.sleep(0.05)

        if len(vals) < 3:
            return None
        return float(median(vals))

def distance_to_percent(distance_cm, full_cm, empty_cm):
    """
    full_cm: distance when tank FULL (smaller)
    empty_cm: distance when tank EMPTY (larger)
    Return 0..100 or None
    """
    if distance_cm is None:
        return None
    full_cm = float(full_cm)
    empty_cm = float(empty_cm)
    if empty_cm <= full_cm:
        return None

    pct = (empty_cm - distance_cm) / (empty_cm - full_cm) * 100.0
    if pct < 0:
        pct = 0.0
    if pct > 100:
        pct = 100.0
    return float(pct)
