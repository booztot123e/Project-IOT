import * as React from "react";
import { useEffect, useRef, useState } from "react";
import {
  Platform,
  SafeAreaView,
  ScrollView,
  View,
  Text,
  TouchableOpacity,
  Alert,
  Dimensions,
  ActivityIndicator,
} from "react-native";
import * as Notifications from "expo-notifications";
import { LineChart } from "react-native-chart-kit";

/* ================= API ================= */
const BASE_URL = "http://192.168.1.23:8000";              // ← เปลี่ยนเป็น IP ของ Pi
const STATUS_URL   = `${BASE_URL}/api/status/summary`;    // สรุปล่าสุดทุก metric
const MINUTES_URL  = (h: number) => `${BASE_URL}/api/minutes?hours=${h}`;
const ALERTS_LATEST_URL = `${BASE_URL}/api/alerts/latest`;
const PUSH_REGISTER_URL = `${BASE_URL}/api/push/register/`; // ต้องมีใน urls.py

type LatestBlock = {
  temp?: { value?: number; temp_f?: number; createdAt?: string };
  current?: { value?: number; unit?: string; createdAt?: string };
  level?: { value?: number; unit?: string; percent?: number; createdAt?: string };
  cycles?: { value?: number; createdAt?: string };
  latest?: any; // กัน schema ต่างเวอร์ชัน
};

type MinuteRow = {
  t_ms: number;
  temp?: number;
  current?: number;
  level?: number;
  cycles?: number;
};

type AlertRow = {
  ts_ms: number;
  metric: string;
  value: number;
  threshold: number;
  severity?: string;
  state?: string;
  message?: string;
};

/* ================ Notifications ================ */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

async function registerForPushNotificationsAsync(): Promise<string | null> {
  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") {
    Alert.alert("Permission", "ไม่ได้รับอนุญาต Notifications");
    return null;
  }
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
  // ถ้าใช้ SDK 49+ แนะนำกำหนด projectId ใน app.json ด้วย
  const token = (await Notifications.getExpoPushTokenAsync()).data;
  return token ?? null;
}

/* ================= Reusable UI ================= */
function Card({
  label,
  value,
  unit,
  sub,
}: {
  label: string;
  value: number | string | null;
  unit?: string;
  sub?: string;
}) {
  return (
    <View
      style={{
        backgroundColor: "#fff",
        borderRadius: 14,
        padding: 14,
        shadowColor: "#000",
        shadowOpacity: 0.05,
        shadowRadius: 6,
        elevation: 2,
        flex: 1,
      }}
    >
      <Text style={{ color: "#6b7280", fontSize: 12 }}>{label}</Text>
      <Text style={{ fontSize: 28, fontWeight: "800", marginTop: 6 }}>
        {value ?? "—"}{unit ? <Text style={{ fontWeight: "600" }}>{unit}</Text> : null}
      </Text>
      {sub ? <Text style={{ color: "#6b7280", marginTop: 4, fontSize: 12 }}>{sub}</Text> : null}
    </View>
  );
}
const btn = (active: boolean) => ({
  borderWidth: 1,
  borderColor: active ? "#111" : "#e5e7eb",
  backgroundColor: active ? "#111" : "#fff",
  paddingVertical: 6,
  paddingHorizontal: 10,
  borderRadius: 10,
} as const);
const btnTxt = (active: boolean) =>
  ({ color: active ? "#fff" : "#111", fontWeight: "700" } as const);

/* ================= Main ================= */
export default function DashboardScreen() {
  const [hours, setHours] = useState<number>(24);
  const [rows, setRows] = useState<MinuteRow[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [source, setSource] = useState<string>("—");
  const [loading, setLoading] = useState(false);

  const [tempC, setTempC] = useState<number | null>(null);
  const [tempF, setTempF] = useState<number | null>(null);
  const [amps, setAmps] = useState<number | null>(null);
  const [level, setLevel] = useState<number | null>(null);
  const [cycles, setCycles] = useState<number | null>(null);

  const notifListener = useRef<any>(null);

  const roundOrNull = (v: any, d = 2) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    const m = Math.pow(10, d);
    return Math.round(n * m) / m;
  };

  /* ---- load summary (ล่าสุด) ---- */
  async function loadStatus() {
    try {
      const r = await fetch(STATUS_URL, { cache: "no-store" });
      const j = await r.json();
      const d: LatestBlock = j?.data || {};
      const latest = d.latest || d; // รองรับ 2 schema

      setTempC(roundOrNull(latest?.temp?.value ?? latest?.temp_c));
      setTempF(
        roundOrNull(
          latest?.temp?.temp_f ??
            (latest?.temp?.value != null ? (latest.temp.value * 9) / 5 + 32 : null)
        )
      );
      setAmps(roundOrNull(latest?.current?.value));
      setLevel(roundOrNull(latest?.level?.value));
      setCycles(
        Number.isFinite(Number(latest?.cycles?.value))
          ? Number(latest?.cycles?.value)
          : null
      );
      setSource("fs"); // มาจาก Firestore summary
    } catch {
      setSource("offline");
    }
  }

  /* ---- load minutes (สำหรับกราฟ) ---- */
  async function loadMinutes(h: number) {
    setHours(h);
    setLoading(true);
    try {
      const r = await fetch(MINUTES_URL(h), { cache: "no-store" });
      const j = await r.json();
      setRows(j?.ok ? j.rows || [] : []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadAlerts() {
    try {
      const r = await fetch(ALERTS_LATEST_URL, { cache: "no-store" });
      const j = await r.json();
      setAlerts(j?.ok ? j.rows || [] : []);
    } catch {
      setAlerts([]);
    }
  }

  useEffect(() => {
    (async () => {
      const token = await registerForPushNotificationsAsync();
      if (token) {
        try {
          await fetch(PUSH_REGISTER_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
        } catch {}
      }
    })();
    notifListener.current = Notifications.addNotificationReceivedListener(() => {});
    return () => notifListener.current?.remove?.();
  }, []);

  useEffect(() => {
    loadStatus();
    loadMinutes(24);
    loadAlerts();
    const t1 = setInterval(loadStatus, 5000);
    const t2 = setInterval(loadAlerts, 15000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, []);

  /* ---- charts config ---- */
  const screenWidth = Dimensions.get("window").width - 32;
  const chartConfig = (r: number, g: number, b: number) => ({
    backgroundColor: "#fff",
    backgroundGradientFrom: "#fff",
    backgroundGradientTo: "#fff",
    color: (opacity = 1) => `rgba(${r},${g},${b},${opacity})`,
    labelColor: () => "#6b7280",
    propsForDots: { r: "0" },
    propsForBackgroundLines: { stroke: "#e5e7eb" },
  });
  const safe = (arr: number[]) => (arr.length ? arr : [0]);

  const temps = rows.map((r) => r.temp ?? 0);
  const currents = rows.map((r) => r.current ?? 0);
  const levels = rows.map((r) => r.level ?? 0);
  const cyc = rows.map((r) => r.cycles ?? 0);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f6f7f8" }}>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        {/* Header */}
        <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <Text style={{ fontSize: 22, fontWeight: "700" }}>IoT Sensor — Mobile</Text>
          <View style={{ marginLeft: "auto", flexDirection: "row", gap: 8 }}>
            <TouchableOpacity onPress={() => loadMinutes(24)} style={btn(hours === 24)}>
              <Text style={btnTxt(hours === 24)}>1d</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => loadMinutes(72)} style={btn(hours === 72)}>
              <Text style={btnTxt(hours === 72)}>3d</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => loadMinutes(168)} style={btn(hours === 168)}>
              <Text style={btnTxt(hours === 168)}>7d</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => { loadStatus(); loadMinutes(hours); }} style={btn(false)}>
              <Text>⟳</Text>
            </TouchableOpacity>
          </View>
        </View>

        <Text style={{ color: "#6b7280", marginTop: 6 }}>
          Source: <Text style={{ fontWeight: "700" }}>{source}</Text> • Records: {rows.length}
        </Text>

        {/* KPIs */}
        <View style={{ marginTop: 12, gap: 12 }}>
          <View style={{ flexDirection: "row", gap: 12 }}>
            <Card label="Temperature" value={tempC} unit="°C" sub={(tempF ?? "—") + "°F"} />
            <Card label="Current" value={amps} unit="A" />
          </View>
          <View style={{ flexDirection: "row", gap: 12 }}>
            <Card label="Level" value={level} unit="cm" />
            <Card label="Cycles" value={cycles} />
          </View>
        </View>

        {/* Alerts (ล่าสุด) */}
        <Text style={{ marginTop: 16, fontWeight: "700" }}>⚠ Recent Alerts</Text>
        {alerts.map((a, i) => (
          <View key={i} style={{ backgroundColor: "#fee2e2", padding: 8, borderRadius: 8, marginTop: 6 }}>
            <Text>{a.metric.toUpperCase()} → {a.message || ""}</Text>
            <Text style={{ fontSize: 12, color: "#6b7280" }}>
              value={a.value} th={a.threshold} ({a.state || "—"})
            </Text>
          </View>
        ))}

        {/* Charts */}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : (
          <>
            <Text style={{ marginTop: 20, fontWeight: "700" }}>Temperature (°C)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(temps) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig(249, 115, 22)}   // #f97316
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Current (A)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(currents) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig(14, 165, 233)}   // #0ea5e9
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Level (cm)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(levels) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig(34, 197, 94)}    // #22c55e
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Cycles</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(cyc) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig(139, 92, 246)}   // #8b5cf6
              style={{ borderRadius: 12, marginTop: 8 }}
            />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
