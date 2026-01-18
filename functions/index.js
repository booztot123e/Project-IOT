const functions = require("firebase-functions");
const admin = require("firebase-admin");
admin.initializeApp();

exports.cleanupOldData = functions.pubsub
  .schedule("every 24 hours")
  .timeZone("Asia/Bangkok")
  .onRun(async () => {

    const db = admin.firestore();

    const sevenDaysAgo = new Date(
      Date.now() - 7 * 24 * 60 * 60 * 1000
    );

    // ดึงทุก device
    const devicesSnap = await db.collection("devices").get();

    for (const device of devicesSnap.docs) {
      const minutesRef = device.ref.collection("minutes");

      const oldDataSnap = await minutesRef
        .where("uploaded_at", "<", sevenDaysAgo.toISOString())
        .get();

      oldDataSnap.forEach(doc => doc.ref.delete());
    }

    return null;
  });
