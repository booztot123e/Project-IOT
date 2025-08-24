#!/usr/bin/env python3
import os, time, django, traceback
from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tempmon.settings")
django.setup()

from sensor.max6675 import get_temp_c
from sensor.models import Reading

INTERVAL_SEC = 10  # เก็บทุก 10 วิ

def main():
    print(f"[collector] start {datetime.now().isoformat()} interval={INTERVAL_SEC}s")
    while True:
        try:
            c = round(float(get_temp_c()), 2)
            f = round(c * 9/5 + 32, 2)
            Reading.objects.create(temp_c=c, temp_f=f)
            print(f"[collector] {datetime.now().isoformat()} -> {c}°C / {f}°F")
        except Exception as e:
            print(f"[collector] ERROR {datetime.now().isoformat()}: {e}")
            traceback.print_exc()
        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
