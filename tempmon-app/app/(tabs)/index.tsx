// app/(tabs)/index.tsx
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import {
  Platform,
  ScrollView,
  View,
  Text,
  TouchableOpacity,
  Alert,
  Dimensions,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { LineChart } from "react-native-chart-kit";

/* ====== Config API ====== */
const BASE_URL = "http://raspberrypi.local:8000"; // แก้เป็น IP/โฮสต์ของ Pi
const LATEST_URL = `${BASE_URL}/api/latest`;
const MINUTES_URL = (h: number) => `${BASE_URL}/api/minutes?hours=${h}`;
const ALERTS_URL = `${BASE_URL}/api/alerts/latest`;
const PUSH_REGISTER_URL = `${BASE_URL}/api/push/register/`;
const PUSH_TEST_URL = `${BASE_URL}/api/push/test/`;

const isExpoGo = Constants.appOwnership === "expo";

/* ====== Types ====== */
type LatestT = {
  temp: number | null;
  current: number | null;
  level: number | null;
  cycles: number | null;
  ts_ms: number | null;
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
  threshold: number | null;
  severity?: string;
  state?: "open" | "closed";
};

/* ====== Notifications (แสดงเฉพาะ local notification; push ข้ามถ้า Expo Go) ====== */
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
  if (isExpoGo) return null; // ⛔️ ข้ามบน Expo Go เพื่อเลี่ยง warning/ข้อจำกัด
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
  const token = (await Notifications.getExpoPushTokenAsync()).data;
  return token ?? null;
}

/* ====== Small helpers ====== */
const roundOrNull = (v: any, d = 2) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  const m = Math.pow(10, d);
  return Math.round(n * m) / m;
};
const chooseSamples = (hours: number) => {
  if (hours <= 6) return 300;
  if (hours <= 48) return 500;
  return 800;
};
// downsample แบบง่าย (avg per bucket) ให้เส้นนุ่ม
function lttb(arr: number[], maxPoints: number) {
  if (arr.length <= maxPoints) return arr;
  const bucket = Math.floor(arr.length / maxPoints);
  const out: number[] = [];
  for (let i = 0; i < arr.length; i += bucket) {
    const slice = arr.slice(i, i + bucket);
    out.push(slice.reduce((a, b) => a + b, 0) / slice.length);
  }
  return out;
}

/* ====== UI bits ====== */
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
        {value ?? "—"}
        {unit ? <Text style={{ fontWeight: "600" }}>{unit}</Text> : null}
      </Text>
      {sub ? (
        <Text style={{ color: "#6b7280", marginTop: 4, fontSize: 12 }}>
          {sub}
        </Text>
      ) : null}
    </View>
  );
}
const btn = (active: boolean) =>
  ({
    borderWidth: 1,
    borderColor: active ? "#111" : "#e5e7eb",
    backgroundColor: active ? "#111" : "#fff",
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 10,
  } as const);
const btnTxt = (active: boolean) =>
  ({ color: active ? "#fff" : "#111", fontWeight: "700" } as const);

/* ====== Screen ====== */
export default function DashboardScreen() {
  const [latest, setLatest] = useState<LatestT>({
    temp: null,
    current: null,
    level: null,
    cycles: null,
    ts_ms: null,
  });
  const [hours, setHours] = useState<number>(24); // default 1d
  const [rows, setRows] = useState<MinuteRow[]>([]);
  const [source, setSource] = useState<string>("—");
  const [loading, setLoading] = useState(false);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const notifListener = useRef<any>(null);

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
    notifListener.current = Notifications.addNotificationReceivedListener(
      () => {}
    );
    return () => {
      if (notifListener.current) notifListener.current.remove();
    };
  }, []);

  async function loadLatest() {
    try {
      const r = await fetch(LATEST_URL, { cache: "no-store" });
      const j = await r.json();
      if (j && j.ok) {
        setLatest({
          temp: roundOrNull(j.temp),
          current: roundOrNull(j.current),
          level: roundOrNull(j.level),
          cycles: Number.isFinite(Number(j.cycles)) ? Number(j.cycles) : null,
          ts_ms: j.ts_ms ?? null,
        });
        setSource("fs"); // หรือ "local" ตามแหล่งจริงที่ใช้
      } else {
        setSource("offline");
      }
    } catch {
      setSource("offline");
    }
  }

  async function loadMinutes(h: number) {
    setHours(h);
    setLoading(true);
    try {
      const r = await fetch(MINUTES_URL(h), { cache: "no-store" });
      const j = await r.json();
      if (j?.ok) setRows(j.rows || []);
      else setRows([]);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadAlerts() {
    setAlertsLoading(true);
    try {
      const r = await fetch(ALERTS_URL, { cache: "no-store" });
      const j = await r.json();
      setAlerts(j?.ok ? j.rows || [] : []);
    } catch {
      setAlerts([]);
    } finally {
      setAlertsLoading(false);
    }
  }

  useEffect(() => {
    loadLatest();
    loadMinutes(24);
    loadAlerts();
    const t = setInterval(loadLatest, 3000);
    return () => clearInterval(t);
  }, []);

  const tempF =
    latest.temp != null ? roundOrNull((latest.temp * 9) / 5 + 32) : "—";

  async function onTestPush() {
    try {
      const r = await fetch(PUSH_TEST_URL);
      const j = await r.json();
      Alert.alert(j?.ok ? "OK" : "Error", j?.ok ? "ส่งแจ้งเตือนแล้ว" : j?.error || "send failed");
    } catch (e) {
      Alert.alert("Error", String(e));
    }
  }

  /* ====== Charts prep ====== */
  const screenWidth = Dimensions.get("window").width - 32;
  const chartConfig = (hex: string) => ({
    backgroundColor: "#fff",
    backgroundGradientFrom: "#fff",
    backgroundGradientTo: "#fff",
    color: (opacity = 1) => {
      const a = Math.round(opacity * 255).toString(16).padStart(2, "0");
      return `${hex}${a}`;
    },
    labelColor: () => "#6b7280",
    propsForDots: { r: "0" },
    propsForBackgroundLines: { stroke: "#e5e7eb" },
  });
  const safe = (arr: number[]) => (arr.length ? arr : [0]);
  const samples = chooseSamples(hours);
  const tempsDs = lttb(rows.map((r) => r.temp ?? 0), samples);
  const currentsDs = lttb(rows.map((r) => r.current ?? 0), samples);
  const levelsDs = lttb(rows.map((r) => r.level ?? 0), samples);
  const cyclesDs = lttb(rows.map((r) => r.cycles ?? 0), samples);

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
            <TouchableOpacity onPress={() => { loadLatest(); loadMinutes(hours); loadAlerts(); }} style={btn(false)}>
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
            <Card label="Temperature" value={latest.temp} unit="°C" sub={`${tempF}°F`} />
            <Card label="Current" value={latest.current} unit="A" />
          </View>
          <View style={{ flexDirection: "row", gap: 12 }}>
            <Card label="Level" value={latest.level} unit="cm" />
            <Card label="Cycles" value={latest.cycles} />
          </View>
        </View>

        {/* Push test (ซ่อนบน Expo Go) */}
        {!isExpoGo && (
          <View style={{ marginTop: 16, flexDirection: "row", gap: 10 }}>
            <TouchableOpacity
              onPress={onTestPush}
              style={{ backgroundColor: "#111", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 10 }}
            >
              <Text style={{ color: "#fff", fontWeight: "700" }}>Send Test Push</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Alerts */}
        <Text style={{ marginTop: 18, fontWeight: "800" }}>⚠ Recent Alerts</Text>
        {alertsLoading ? (
          <ActivityIndicator style={{ marginTop: 8 }} />
        ) : alerts.length ? (
          alerts.slice(0, 10).map((a, i) => (
            <View key={i} style={{ flexDirection: "row", gap: 8, alignItems: "center", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#eee" }}>
              <Text style={{ fontSize: 10, backgroundColor: a.state === "open" ? "#fee2e2" : "#e5f6ed", color: a.state === "open" ? "#b91c1c" : "#16a34a", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999 }}>
                {a.state || "open"}
              </Text>
              <Text style={{ fontWeight: "700" }}>{a.metric}</Text>
              <Text>value={roundOrNull(a.value)}</Text>
              {a.threshold != null && <Text> th={a.threshold}</Text>}
              {!!a.severity && <Text style={{ color: "#6b7280" }}> ({a.severity.toUpperCase()})</Text>}
              <Text style={{ marginLeft: "auto", color: "#6b7280" }}>
                {new Date(a.ts_ms).toLocaleString()}
              </Text>
            </View>
          ))
        ) : (
          <Text style={{ color: "#6b7280", marginTop: 6 }}>No alerts</Text>
        )}

        {/* Charts */}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 20 }} />
        ) : (
          <>
            <Text style={{ marginTop: 20, fontWeight: "700" }}>Temperature (°C)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(tempsDs) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig("#f97316")}
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Current (A)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(currentsDs) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig("#0ea5e9")}
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Level (cm)</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(levelsDs) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig("#22c55e")}
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />

            <Text style={{ marginTop: 20, fontWeight: "700" }}>Cycles</Text>
            <LineChart
              data={{ labels: [], datasets: [{ data: safe(cyclesDs) }] }}
              width={screenWidth}
              height={200}
              chartConfig={chartConfig("#8b5cf6")}
              style={{ borderRadius: 12, marginTop: 8 }}
            />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
