/**
 * LeadFlow Cloudflare Worker Middleware (Always-Online Relay)
 * 
 * 1. Deploy this worker to your Cloudflare account.
 * 2. Bind a KV namespace named 'LEADFLOW_KV' to this worker.
 * 3. Set the SECRET_TOKEN and NTFY_TOPIC environment variables in Wrangler/Cloudflare Dashboard.
 * 4. Put your Worker's URL in your .env under LEADFLOW_PUBLIC_URL.
 */

const SECRET_TOKEN = "lf_sec_9e21808ccce4d37"; // Securely auto-generated

const PIXEL_GIF = new Uint8Array([
  0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00, 0xff, 0xff, 0xff,
  0x00, 0x00, 0x00, 0x21, 0xf9, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0x2c, 0x00, 0x00, 0x00, 0x00,
  0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02, 0x44, 0x01, 0x00, 0x3b
]);

async function notifyNtfy(message, env, title = "LeadFlow Relay") {
  const topic = env.NTFY_TOPIC;
  if (!topic) return;
  try {
    const res = await fetch(`https://ntfy.sh/${topic}`, {
      method: "POST",
      body: message,
      headers: {
        "Title": title,
        "Priority": "4", // High priority
        "Tags": "incoming_envelope,bell",
        "User-Agent": "LeadFlowRelayWorker/1.0"
      }
    });
    console.log(`Ntfy response status: ${res.status} (${res.statusText})`);
    if (!res.ok) {
      const text = await res.text();
      console.error(`Ntfy error body: ${text}`);
    }
  } catch (e) {
    console.error("Failed to send ntfy notification:", e);
  }
}

async function notifyTelegram(message, env) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const userId = env.TELEGRAM_USER_ID;
  if (!token || !userId) return;
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: userId,
        text: message
      })
    });
    console.log(`Telegram response status: ${res.status}`);
  } catch (e) {
    console.error("Failed to send Telegram notification:", e);
  }
}

async function notifyAll(message, env, title = "LeadFlow Relay") {
  await Promise.allSettled([
    notifyNtfy(message, env, title),
    notifyTelegram(`<b>[${title}]</b>\n${message}`, env)
  ]);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method;

    // CORS preflight
    if (method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Secret-Token"
        }
      });
    }

    // ── Heartbeat API for Mac/Firestick failover coordination ───────────────────
    if (url.pathname === "/api/heartbeat") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      const device = url.searchParams.get("device") || "primary";

      if (method === "POST") {
        const body = await request.json().catch(() => ({}));
        const timestamp = body.timestamp || Date.now();
        await env.LEADFLOW_KV.put(`heartbeat:${device}`, String(timestamp));
        return new Response(JSON.stringify({ success: true, timestamp, device }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      } else {
        const val = await env.LEADFLOW_KV.get(`heartbeat:${device}`);
        return new Response(JSON.stringify({ timestamp: val ? parseInt(val) : 0, device }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      }
    }

    // ── Database Sync/Replication API ───────────────────────────────────────────
    if (url.pathname === "/api/sync") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (method === "POST") {
        const body = await request.json().catch(() => ({}));
        const transactions = body.transactions || [];
        
        for (const tx of transactions) {
          // Generate a unique chronological ID: timestamp_random
          const txId = `${Date.now()}_${Math.floor(Math.random() * 10000)}`;
          tx.seq = txId;
          await env.LEADFLOW_KV.put(`sync:log:${txId}`, JSON.stringify(tx));
        }

        return new Response(JSON.stringify({ success: true, count: transactions.length }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      } else {
        const since = url.searchParams.get("since") || "0";
        
        // List sync log keys
        const list = await env.LEADFLOW_KV.list({ prefix: "sync:log:" });
        const results = [];

        for (const key of list.keys) {
          // Key name: sync:log:<timestamp>_<random>
          const txId = key.name.substring(9); // remove "sync:log:"
          
          if (txId > since) {
            const val = await env.LEADFLOW_KV.get(key.name);
            if (val) {
              try {
                results.push(JSON.parse(val));
              } catch (e) {
                results.push({ raw: val, seq: txId });
              }
            }
          }
        }

        // Sort chronologically by sequence ID
        results.sort((a, b) => (a.seq > b.seq ? 1 : -1));

        return new Response(JSON.stringify({ transactions: results }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      }
    }

    // ── 1. API: Retrieve & Flush Events (Mac polling) ───────────────────────────
    if (url.pathname === "/api/events") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;
      const peek = url.searchParams.get("peek") === "true";

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      // List all stored keys in KV
      const list = await env.LEADFLOW_KV.list({ prefix: "event:" });
      const events = [];

      for (const key of list.keys) {
        const val = await env.LEADFLOW_KV.get(key.name);
        if (val) {
          try {
            const parsed = JSON.parse(val);
            parsed._key = key.name;
            events.push(parsed);
          } catch (e) {
            events.push({ raw: val, key: key.name, _key: key.name });
          }
          // Delete from KV immediately after reading to clear the queue unless peeking
          if (!peek) {
            await env.LEADFLOW_KV.delete(key.name);
          }
        }
      }

      return new Response(JSON.stringify(events), {
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }

    // ── 2. Open Tracking Pixel ──────────────────────────────────────────────────
    if (url.pathname.startsWith("/track/open/")) {
      const trackingId = url.pathname.split("/").pop();
      const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
      const payload = {
        type: "open",
        tracking_id: trackingId,
        timestamp: new Date().toISOString()
      };

      await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));
      
      // Send real-time notification
      await notifyAll(`✉️ Email opened! (ID: ${trackingId})`, env, "Leadflow Open");

      return new Response(PIXEL_GIF, {
        headers: {
          "Content-Type": "image/gif",
          "Cache-Control": "no-cache, no-store, must-revalidate",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }

    // ── 3. Click Tracking Redirect ──────────────────────────────────────────────
    if (url.pathname.startsWith("/track/click/")) {
      const trackingId = url.pathname.split("/").pop();
      const targetUrl = url.searchParams.get("url") || "/";
      const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
      const payload = {
        type: "click",
        tracking_id: trackingId,
        redirect_url: targetUrl,
        timestamp: new Date().toISOString()
      };

      await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));

      // Send real-time notification
      await notifyAll(`🖱️ Demo link clicked! Redirecting prospect...`, env, "Leadflow Click");

      return Response.redirect(targetUrl, 302);
    }

    // ── 4. Scroll & Engagement Pings (from Demo sites) ──────────────────────────
    if (url.pathname === "/api/engage" || url.pathname === "/api/track.png") {
      const bid = url.searchParams.get("bid");
      const ev = url.searchParams.get("ev") || "open"; // default to open for legacy track.png
      
      const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
      const payload = {
        type: "engage",
        business_id: bid ? parseInt(bid, 10) : 0,
        event_type: ev,
        timestamp: new Date().toISOString()
      };

      await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));

      // Send real-time notification for high-intent actions
      if (ev === "scroll_90") {
        await notifyAll(`🔥 Hot Lead! Prospect read 90%+ of your demo site (Biz ID: ${bid})`, env, "Leadflow Hot Engagement");
      } else if (ev === "modal_shown") {
        await notifyAll(`💬 Contact Modal Opened! (Biz ID: ${bid})`, env, "Leadflow Engagement");
      }

      // Return a transparent 1x1 GIF for compatibility with image tags
      return new Response(PIXEL_GIF, {
        headers: {
          "Content-Type": "image/gif",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }

    // Fallback: Status page
    return new Response(JSON.stringify({ status: "online", service: "leadflow-relay" }), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
