import { Stack } from 'expo-router';
import * as React from 'react';

export default function RootLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      {/* โฟลเดอร์ (tabs) จะถูกเรนเดอร์ใน Stack หลัก */}
      <Stack.Screen name="(tabs)" />
      {/* ถ้ามี modal แยก ก็เพิ่ม <Stack.Screen name="modal" options={{ presentation: 'modal' }} /> */}
    </Stack>
  );
}
