import sqlite3

conn = sqlite3.connect("sensor.db")  
cursor = conn.cursor()

cursor.execute("""
DELETE FROM sensor_data
WHERE datetime(created_at) < datetime('now', '-7 days')
""")

conn.commit()
conn.close()

print("ลบข้อมูลที่เก่ากว่า 7 วันเรียบร้อย")
