import React, { useEffect, useMemo, useState } from "react";
import { SafeAreaView, View, Text, ScrollView, RefreshControl, ActivityIndicator, Alert, Dimensions } from "react-native";
import { LineChart } from "react-native-chart-kit";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { StatusBar } from "expo-status-bar";

import { initializeApp, getApps } from "firebase/app";
import { getFirestore, doc, onSnapshot, collection, query, orderBy, limit, getDocs } from "firebase/firestore";

/** ===== 1) ใส่ CONFIG โปรเจกต์ใหม่ของมึงให้ถูก ===== */
const firebaseConfig = {
  apiKey: "AIzaSyAGhaL-xYe2z0X8O2_ve0JG45LT2copdec",
  authDomain: "iot-demo-present.firebaseapp.com",
  projectId: "iot-demo-present",
  storageBucket: "iot-demo-present.appspot.com",   // <- สำคัญ! ต้องลงท้าย .appspot.com
  messagingSenderId: "318004360778",
  appId: "1:318004360778:web:27c0a7036a318d796518b3",
  measurementId: "G-QXN9FD4PG2"
};

/** กัน init ซ้ำตอน hot-reload */
const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
const db = getFirestore(app);

/** ===== 2) ตั้งค่า DEVICE_ID ให้ตรงกับที่ Pi เขียน ===== */
const DEVICE_ID = "pi5-001";

/** ===== util ===== */
const screenWidth = Dimensions.get("window").width;
const toNum = (x, fb = null) => (Number.isFinite(Number(x)) ? Number(x) : fb);
const niceTime = (ts) => new Date(ts).toLocaleString();

function useChartData(rows, field) {
  return useMemo(() => {
    const pts = rows
      .map((r) => ({ t: r.t ?? r.timestamp ?? r.createdAt?.toMillis?.(), v: toNum(r[field]) }))
      .filter((p) => p.t && p.v != null);
    if (pts.length < 2) return { labels: ["-", "-"], datasets: [{ data: [0, 0] }] };
    return {
      labels: pts.map((p) => new Date(p.t).toLocaleTimeString()),
      datasets: [{ data: pts.map((p) => p.v) }],
    };
  }, [rows, field]);
}

/** ===== UI ===== */
function StatCard({ title, value, unit, subtitle }) {
  return (
    <View style={{ backgroundColor: "#fff", borderRadius: 16, padding: 16, marginBottom: 12, shadowOpacity: 0.06, shadowRadius: 8 }}>
      <Text style={{ color: "#6b7280", fontSize: 12 }}>{subtitle ?? "Latest"}</Text>
      <Text style={{ color: "#111827", fontSize: 18, fontWeight: "600", marginTop: 4 }}>{title}</Text>
      <Text style={{ fontSize: 28, fontWeight: "800", marginTop: 8 }}>
        {value}{unit ? <Text style={{ color: "#6b7280", fontSize: 18 }}> {unit}</Text> : null}
      </Text>
    </View>
  );
}
function Section({ title, children }) {
  return (
    <View style={{ marginBottom: 16 }}>
      <Text style={{ fontSize: 18, fontWeight: "700", marginBottom: 8 }}>{title}</Text>
      {children}
    </View>
  );
}

export default function App() {
  const [latest, setLatest] = useState({});
  const [histTemp, setHistTemp] = useState([]);
  const [histAmp, setHistAmp] = useState([]);
  const [histLevel, setHistLevel] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  /** ===== 3) ฟัง realtime: /sensors/{id}/live/current ===== */
  useEffect(() => {
    const liveRef = doc(db, "sensors", DEVICE_ID, "live", "current");
    const unsub = onSnapshot(liveRef, (snap) => {
      const d = snap.data();
      if (!d) return;
      setLatest({
        timestamp: d.timestamp?.toMillis ? d.timestamp.toMillis() : (d.timestamp ?? Date.now()),
        temp_c: toNum(d.temp_c),
        current_a: toNum(d.current_a),
        oil_level: toNum(d.oil_level),
        cycle_count: toNum(d.cycle_count),
      });
    });
    return unsub;
  }, []);

  /** ===== 4) โหลดประวัติจาก /sensors/{id}/minutes (ถ้ามี) =====
   * เอกสารนาทีของมึงอาจมีโครง { avg, min, max, samples[], createdAt }
   * โค้ดนี้จะพยายามใช้ avg ถ้ามี ไม่งั้นเอาจุดแรกจาก samples
   */
  const fetchHistory = async () => {
    try {
      const minutesCol = collection(db, "sensors", DEVICE_ID, "minutes");
      const snap = await getDocs(query(minutesCol, orderBy("createdAt", "desc"), limit(60))); // ~60 นาทีล่าสุด
      const rows = snap.docs.map((d) => ({ id: d.id, ...d.data() })).reverse();

      const toRow = (r, fieldName) => {
        // ถ้ากดมาจาก avg/min/max
        if (r[fieldName] != null) return { t: r.createdAt?.toMillis?.() ?? Date.now(), [fieldName]: Number(r[fieldName]) };
        // ลองหยิบจาก samples จุดแรก
        const s0 = Array.isArray(r.samples) && r.samples.length ? r.samples[0] : null;
        if (s0?.v != null) return { t: (s0.t * 1000) || Date.now(), [fieldName]: Number(s0.v) };
        return null;
      };

      const temps  = rows.map((r) => toRow({ ...r, temp_c: r.avg }, "temp_c")).filter(Boolean);
      const amps   = rows.map((r) => toRow({ ...r, current_a: r.avgA ?? r.avg_current }, "current_a")).filter(Boolean);
      const levels = rows.map((r) => toRow({ ...r, oil_level: r.avgL ?? r.avg_level }, "oil_level")).filter(Boolean);

      setHistTemp(temps);
      setHistAmp(amps);
      setHistLevel(levels);
    } catch (e) {
      Alert.alert("Fetch error", String(e?.message || e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { fetchHistory(); }, []);
  const onRefresh = () => { setRefreshing(true); fetchHistory(); };

  /** ===== 5) ชุดข้อมูลสำหรับกราฟ ===== */
  const chartTemp  = useChartData(histTemp,  "temp_c");
  const chartAmp   = useChartData(histAmp,   "current_a");
  const chartLevel = useChartData(histLevel, "oil_level");

  const latestTimeStr = latest?.timestamp ? niceTime(latest.timestamp) : "-";
  const fmt = (n, d = 1) => (Number.isFinite(Number(n)) ? Number(n).toFixed(d) : "-");

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1, backgroundColor: "#f4f4f5" }}>
        <StatusBar style="dark" />
        <ScrollView style={{ paddingHorizontal: 16, paddingTop: 12 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
          <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 12 }}>BAMBOO II-L • IoT Dashboard</Text>

          {loading ? (
            <View style={{ alignItems: "center", paddingVertical: 24 }}>
              <ActivityIndicator />
            </View>
          ) : (
            <View>
              <StatCard title="Temperature" value={fmt(latest.temp_c, 1)} unit="°C" subtitle={latestTimeStr} />
              <StatCard title="Current"     value={fmt(latest.current_a, 2)} unit="A" />
              <StatCard title="Oil level"   value={fmt(latest.oil_level, 1)} unit="cm" />
              <StatCard title="Cycle count" value={Number.isFinite(Number(latest?.cycle_count)) ? String(latest.cycle_count) : "-"} unit="times" />
            </View>
          )}

          {/* ===== Charts (จะแสดงเมื่อมี minutes data) ===== */}
          <Section title="Temperature (°C)">
            <LineChart
              data={chartTemp}
              width={screenWidth - 32}
              height={220}
              yAxisSuffix="°C"
              chartConfig={{
                backgroundGradientFrom: "#fff",
                backgroundGradientTo: "#fff",
                decimalPlaces: 1,
                color: (o = 1) => `rgba(0,0,0,${o})`,
                labelColor: (o = 1) => `rgba(0,0,0,${o})`,
                propsForBackgroundLines: { strokeDasharray: "3 6" },
              }}
              bezier
              style={{ borderRadius: 16 }}
            />
          </Section>

          <Section title="Current (A)">
            <LineChart
              data={chartAmp}
              width={screenWidth - 32}
              height={220}
              yAxisSuffix="A"
              chartConfig={{
                backgroundGradientFrom: "#fff",
                backgroundGradientTo: "#fff",
                decimalPlaces: 2,
                color: (o = 1) => `rgba(0,0,0,${o})`,
                labelColor: (o = 1) => `rgba(0,0,0,${o})`,
                propsForBackgroundLines: { strokeDasharray: "3 6" },
              }}
              bezier
              style={{ borderRadius: 16 }}
            />
          </Section>

          <Section title="Oil Level (cm)">
            <LineChart
              data={chartLevel}
              width={screenWidth - 32}
              height={220}
              yAxisSuffix="cm"
              chartConfig={{
                backgroundGradientFrom: "#fff",
                backgroundGradientTo: "#fff",
                decimalPlaces: 1,
                color: (o = 1) => `rgba(0,0,0,${o})`,
                labelColor: (o = 1) => `rgba(0,0,0,${o})`,
                propsForBackgroundLines: { strokeDasharray: "3 6" },
              }}
              bezier
              style={{ borderRadius: 16 }}
            />
          </Section>

          <View style={{ height: 24 }} />
        </ScrollView>
      </SafeAreaView>
    </GestureHandlerRootView>
  );
}
