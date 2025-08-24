from django.db import models

class Reading(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    temp_c = models.FloatField(null=True, blank=True)
    temp_f = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]  # query แถวล่าสุดง่ายขึ้น

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} · {self.temp_c}°C"
