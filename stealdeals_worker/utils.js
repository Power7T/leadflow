// utils.js – shared helper functions for the Stealdeals Worker

// Notification helpers (Telegram, ntfy)
export async function notifyNtfy(message, env, title = "Stealdeals Relay") {
  const topic = env.NTFY_TOPIC;
  if (!topic) return;
  try {
    const res = await fetch(`https://ntfy.sh/${topic}`, {
      method: "POST",
      body: message,
      headers: {
        "Title": title,
        "Priority": "4",
        "Tags": "incoming_envelope,bell",
        "User-Agent": "StealdealsRelayWorker/1.0"
      }
    });
    if (!res.ok) {
      const txt = await res.text();
      console.error(`ntfy error: ${res.status} ${txt}`);
    }
  } catch (e) {
    console.error("notifyNtfy failed", e);
  }
}

export async function notifyTelegram(message, env) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const userId = env.TELEGRAM_USER_ID;
  if (!token || !userId) return;
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: userId, text: message })
    });
    if (!res.ok) {
      const txt = await res.text();
      console.error(`Telegram error: ${res.status} ${txt}`);
    }
  } catch (e) {
    console.error("notifyTelegram failed", e);
  }
}

export async function notifyAll(message, env, title = "Stealdeals Relay") {
  await Promise.allSettled([
    notifyNtfy(message, env, title),
    notifyTelegram(`<b>[${title}]</b>\n${message}`, env)
  ]);
}

// Tiny 1x1 transparent GIF (used for tracking pixels)
export const PIXEL_GIF = new Uint8Array([
  0x47,0x49,0x46,0x38,0x39,0x61,0x01,0x00,0x01,0x00,0x80,0x00,0x00,0xff,0xff,0xff,
  0x00,0x00,0x00,0x21,0xf9,0x04,0x01,0x00,0x00,0x00,0x00,0x2c,0x00,0x00,0x00,0x00,
  0x01,0x00,0x01,0x00,0x00,0x02,0x02,0x44,0x01,0x00,0x3b
]);
