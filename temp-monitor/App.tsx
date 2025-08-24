import { useEffect, useState } from "react";
import {
  SafeAreaView,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from "react-native";
import { StatusBar } from "expo-status-bar";

type TempResp = {
  timestamp?: string;
  temp_c?: number;
  temp_f?: number;
  error?: string;
};

const DEFAULT_BASE = "http://192.168.1.129:8000"; // 👈 แก้เป็น IP ของ Pi มึง เช่น http://192.168.1.129:8000

export default function App() {
  const [base, setBase] = useState(DEFAULT_BASE);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<TempResp | null>(null);

  const fetchOnce = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${base}/api/temp`);
      const j: TempResp = await res.json();
      setData(j);
      if (!res.ok) throw new Error(j?.error || `HTTP ${res.status}`);
    } catch (e: any) {
      Alert.alert("Fetch failed", String(e?.message || e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOnce();
    const id = setInterval(fetchOnce, 5000); // อัปเดตทุก 5 วิ
    return () => clearInterval(id);
  }, [base]);

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" />
      <Text style={styles.title}>MAX6675 · Temp Monitor</Text>

      {/* API Base URL */}
      <View style={styles.card}>
        <Text style={styles.label}>API Base URL</Text>
        <TextInput
          value={base}
          onChangeText={setBase}
          autoCapitalize="none"
          placeholder="http://<IP_Pi>:8000"
          placeholderTextColor="#94a3b8"
          style={styles.input}
        />
        <TouchableOpacity onPress={fetchOnce} style={styles.button}>
          <Text style={styles.buttonText}>{loading ? "Loading..." : "Test Connection"}</Text>
        </TouchableOpacity>
      </View>

      {/* Result */}
      <View style={styles.resultCard}>
        {loading && !data ? (
          <ActivityIndicator />
        ) : data?.error ? (
          <Text style={styles.error}>Error: {data.error}</Text>
        ) : (
          <>
            <Text style={styles.subtitle}>สถานะ: ปกติ</Text>
            <Text style={styles.tempMain}>
              {data?.temp_c ?? "-"} °C
            </Text>
            <Text style={styles.tempSub}>
              {data?.temp_f ?? "-"} °F
            </Text>
            <Text style={styles.timestamp}>
              {data?.timestamp ? data.timestamp.replace("T", " ").slice(0, 19) : ""}
            </Text>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220", padding: 16, gap: 16 },
  title: { color: "white", fontSize: 22, fontWeight: "800" },
  card: { gap: 8, borderWidth: 1, borderColor: "#1f2937", backgroundColor: "#0d1b2a", borderRadius: 16, padding: 16 },
  label: { color: "#cbd5e1" },
  input: { borderWidth: 1, borderColor: "#334155", borderRadius: 12, padding: 12, color: "white" },
  button: { backgroundColor: "white", padding: 12, borderRadius: 12, marginTop: 4 },
  buttonText: { textAlign: "center", fontWeight: "700" },
  resultCard: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#1f2937",
    backgroundColor: "#0a2b2b",
    borderRadius: 16,
    padding: 24,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  subtitle: { color: "#a7f3d0", fontSize: 16 },
  tempMain: { color: "white", fontSize: 64, fontWeight: "900" },
  tempSub: { color: "#93c5fd", fontSize: 18 },
  timestamp: { color: "#94a3b8", marginTop: 4 },
  error: { color: "#fecaca" },
});
