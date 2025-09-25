import * as React from 'react';
import { SafeAreaView, View, Text } from 'react-native';

export default function ExploreScreen() {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#f6f7f8' }}>
      <View style={{ padding: 16 }}>
        <Text style={{ fontSize: 22, fontWeight: '700' }}>Explore</Text>
        <Text style={{ marginTop: 8, color: '#6b7280' }}>
          หน้านี้เผื่อทำ Settings / Alert rules / Device switch ฯลฯ
        </Text>
      </View>
    </SafeAreaView>
  );
}
