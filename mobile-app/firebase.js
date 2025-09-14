// firebase.js
import { initializeApp, getApps } from "firebase/app";
import { initializeAuth, getReactNativePersistence } from "firebase/auth";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { getFirestore } from "firebase/firestore";

// 👉 เอา config ของโปรเจกต์ Firebase ใหม่ (iot-demo-present) มาใส่ตรงนี้
const firebaseConfig = {
  apiKey: "AIzaSyAGhaL-xYe2z0X8O2_ve0JG45LT2copdec",
  authDomain: "iot-demo-present.firebaseapp.com",
  projectId: "iot-demo-present",
  storageBucket: "iot-demo-present.firebasestorage.app",
  messagingSenderId: "318004360778",
  appId: "1:318004360778:web:27c0a7036a318d796518b3",
  measurementId: "G-QXN9FD4PG2"
};

// init app (ใช้ getApps() กันซ้ำ)
export const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);

// init auth สำหรับ React Native (ใช้ AsyncStorage)
export const auth = initializeAuth(app, {
  persistence: getReactNativePersistence(AsyncStorage),
});

// init firestore
export const db = getFirestore(app);
