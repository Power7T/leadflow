// stealdeals_worker/index.js – All‑in‑one Cloudflare Worker for Stealdeals bot logic

import { notifyAll, PIXEL_GIF } from "./utils.js";

// A static fallback token (should be overridden by a secret in the dashboard)
const DEFAULT_TOKEN = ""; // Read from env.SECRET_TOKEN binding — never hardcode

/** Helper: verify the secret token supplied via header or query */
function verify(request, env) {
  const url = new URL(request.url);
  const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
  const configured = env.SECRET_TOKEN || DEFAULT_TOKEN;
  return headerToken === configured;
}

/** Heartbeat – used by Mac/FireStick for fail‑over coordination */
async function handleHeartbeat(request, env) {
  if (!verify(request, env)) return new Response("Unauthorized", { status: 401 });
  const url = new URL(request.url);
  const device = url.searchParams.get("device") || "primary";

  if (request.method === "POST") {
    const body = await request.json().catch(() => ({}));
    const ts = body.timestamp || Date.now();
    await env.LEADFLOW_KV.put(`heartbeat:${device}`, String(ts));
    return new Response(JSON.stringify({ success: true, timestamp: ts, device }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    });
  } else {
    const val = await env.LEADFLOW_KV.get(`heartbeat:${device}`);
    return new Response(JSON.stringify({ timestamp: val ? parseInt(val) : 0, device }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    });
  }
}

/** Sync – simple transaction log store/retrieve */
async function handleSync(request, env) {
  if (!verify(request, env)) return new Response("Unauthorized", { status: 401 });
  const url = new URL(request.url);

  if (request.method === "POST") {
    const body = await request.json().catch(() => ({}));
    const transactions = body.transactions || [];
    for (const tx of transactions) {
      const txId = `${Date.now()}_${Math.floor(Math.random() * 10000)}`;
      tx.seq = txId;
      await env.LEADFLOW_KV.put(`sync:log:${txId}`, JSON.stringify(tx));
    }
    return new Response(JSON.stringify({ success: true, count: transactions.length }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    });
  } else {
    const since = url.searchParams.get("since") || "0";
    const list = await env.LEADFLOW_KV.list({ prefix: "sync:log:" });
    const results = [];
    for (const key of list.keys) {
      const txId = key.name.substring(9); // remove "sync:log:"
      if (txId > since) {
        const val = await env.LEADFLOW_KV.get(key.name);
        if (val) {
          try { results.push(JSON.parse(val)); }
          catch { results.push({ raw: val, seq: txId }); }
        }
      }
    }
    results.sort((a, b) => (a.seq > b.seq ? 1 : -1));
    return new Response(JSON.stringify({ transactions: results }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    });
  }
}

/** Events – retrieve (and optionally flush) stored event blobs */
async function handleEvents(request, env) {
  if (!verify(request, env)) return new Response("Unauthorized", { status: 401 });
  const url = new URL(request.url);
  const peek = url.searchParams.get("peek") === "true";
  const list = await env.LEADFLOW_KV.list({ prefix: "event:" });
  const events = [];
  for (const key of list.keys) {
    const val = await env.LEADFLOW_KV.get(key.name);
    if (val) {
      try { const parsed = JSON.parse(val); parsed._key = key.name; events.push(parsed); }
      catch { events.push({ raw: val, key: key.name, _key: key.name }); }
      if (!peek) await env.LEADFLOW_KV.delete(key.name);
    }
  }
  return new Response(JSON.stringify(events), {
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
  });
}

/** Open‑tracking pixel */
async function handleOpen(request, env) {
  const trackingId = request.params?.id || request.url.split("/").pop();
  const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const payload = { type: "open", tracking_id: trackingId, timestamp: new Date().toISOString() };
  await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));
  await notifyAll(`✉️ Email opened! (ID: ${trackingId})`, env, "Stealdeals Open");
  return new Response(PIXEL_GIF, {
    headers: { "Content-Type": "image/gif", "Cache-Control": "no-cache, no-store, must-revalidate", "Access-Control-Allow-Origin": "*" }
  });
}

/** Click‑redirect */
async function handleClick(request, env) {
  const trackingId = request.params?.id || request.url.split("/").pop();
  const urlObj = new URL(request.url);
  const targetUrl = urlObj.searchParams.get("url") || "/";
  const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const payload = {
    type: "click",
    tracking_id: trackingId,
    redirect_url: targetUrl,
    timestamp: new Date().toISOString()
  };
  await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));
  await notifyAll(`🖱️ Demo link clicked! Redirecting prospect...`, env, "Stealdeals Click");
  return Response.redirect(targetUrl, 302);
}

/** Engagement / scroll pings */
async function handleEngage(request, env) {
  const urlObj = new URL(request.url);
  const bid = urlObj.searchParams.get("bid");
  const ev = urlObj.searchParams.get("ev") || "open";
  const eventId = `event:${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const payload = {
    type: "engage",
    business_id: bid ? parseInt(bid, 10) : 0,
    event_type: ev,
    timestamp: new Date().toISOString()
  };
  await env.LEADFLOW_KV.put(eventId, JSON.stringify(payload));
  if (ev === "scroll_90") {
    await notifyAll(`🔥 Hot Lead! Prospect read 90%+ of your demo site (Biz ID: ${bid})`, env, "Stealdeals Hot Engagement");
  } else if (ev === "modal_shown") {
    await notifyAll(`💬 Contact Modal Opened! (Biz ID: ${bid})`, env, "Stealdeals Engagement");
  }
  return new Response(PIXEL_GIF, { headers: { "Content-Type": "image/gif", "Access-Control-Allow-Origin": "*" } });
}

/** Cuelinks short‑link conversion – expects JSON {"url": "https://…"} */
async function handleLinkConvert(request, env) {
  if (request.method !== "POST") return new Response("Method Not Allowed", { status: 405 });
  const { url } = await request.json().catch(() => ({}));
  if (!url) return new Response(JSON.stringify({ error: "missing url" }), { status: 400, headers: { "Content-Type": "application/json" } });
  const apiKey = env.CUE_LINKS_API_KEY;
  const apiUrl = `https://www.cuelinks.com/api/v2/convert?url=${encodeURIComponent(url)}`;
  const res = await fetch(apiUrl, { headers: { Authorization: `Token token="${apiKey}"` } });
  if (!res.ok) return new Response(JSON.stringify({ error: "cuelinks failure" }), { status: 502, headers: { "Content-Type": "application/json" } });
  const data = await res.json();
  return new Response(JSON.stringify({ converted: data.short_link }), { headers: { "Content-Type": "application/json" } });
}

/** Daily digest – runs as a cron (22:00 IST ≈ 16:00 UTC). */
export async function sendDailyDigest(env) {
  const raw = await env.LEADFLOW_KV.get("deals_today");
  if (!raw) return; // nothing to send
  let deals;
  try { deals = JSON.parse(raw); } catch { return; }
  const top5 = deals.items
    .sort((a, b) => b.discount_pct - a.discount_pct)
    .slice(0, 5)
    .map((d, i) => `${i + 1}. ${d.text.split("\n")[0]} — *${d.discount_pct}% OFF*`)
    .join("\n");
  const msg = `🏆 *Today's Best Deals*\n${top5}\n\n📲 More deals → ${env.INVITE_LINK || ""}`;
  await notifyAll(msg, env, "Stealdeals Daily Digest");
}

/** Weekly report – cron on Sunday 20:00 IST (14:00 UTC). */
export async function sendWeeklyReport(env) {
  const apiKey = env.CUE_LINKS_API_KEY;
  const base = "https://www.cuelinks.com/api/v2";
  const now = new Date();
  const weekStart = new Date(now);
  weekStart.setDate(now.getDate() - now.getDay()); // Monday
  const params = new URLSearchParams({
    start_date: weekStart.toISOString().slice(0, 10),
    end_date: now.toISOString().slice(0, 10)
  });
  const res = await fetch(`${base}/transactions?${params}`, {
    headers: { Authorization: `Token token="${apiKey}"` }
  });
  if (!res.ok) return;
  const data = await res.json();
  const total = data.reduce((s, t) => s + (parseFloat(t.commission) || 0), 0);
  const report = `📊 *Cuelinks Weekly Report*\n_${weekStart.toLocaleDateString()} – ${now.toLocaleDateString()}_\n━━━━━━━━\n💸 Conversions: *${data.length}*\n💰 Est. Commission: *₹${total.toFixed(2)}*`;
  await notifyAll(report, env, "Stealdeals Weekly Report");
}

/** Main fetch handler – routes based on pathname */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    // CORS preflight handling
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Secret-Token"
        }
      });
    }

    // Routing table (order matters)
    if (pathname === "/api/heartbeat") return handleHeartbeat(request, env);
    if (pathname === "/api/sync") return handleSync(request, env);
    if (pathname === "/api/events") return handleEvents(request, env);
    if (pathname.startsWith("/track/open/")) return handleOpen(request, env);
    if (pathname.startsWith("/track/click/")) return handleClick(request, env);
    if (pathname === "/api/engage" || pathname === "/api/track.png") return handleEngage(request, env);
    if (pathname === "/api/link/convert") return handleLinkConvert(request, env);

    // Fallback status page
    return new Response(JSON.stringify({ status: "online", service: "stealdeals-worker" }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    });
  },

  // The following two methods are invoked by Cloudflare cron triggers (see wrangler.toml)
  async scheduled(event, env) {
    // Cloudflare passes the cron name via event.cron (e.g., "daily-digest")
    if (event.cron === "daily-digest") {
      await sendDailyDigest(env);
    } else if (event.cron === "weekly-report") {
      await sendWeeklyReport(env);
    }
  }
};
