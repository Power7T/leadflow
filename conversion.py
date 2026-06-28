"""
Conversion layer for demo sites.

Turns demo *viewers* into booked clients. Injected into every generated demo,
it adds three things on top of the static site:

  1. A sticky "book a call" CTA bar that slides up after the visitor scrolls in.
  2. An exit-intent / timed modal that fires once, asking them to book the build.
  3. Engagement beacons (scroll depth + CTA clicks) sent back to LeadFlow so the
     operator gets a real-time ntfy ping the moment a prospect shows buying intent.
  4. An interactive "Demo Control Center" slide-out sidebar that compares performance
     scores and lets prospects preview different theme brand colors dynamically.

The booking link is static (env-configured) so it works even though demos are
served as static files on GitHub Pages. The engagement beacon points at the
current Cloudflare tunnel; if the tunnel is stale it fails silently (no-cors).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from deploy import public_base

load_dotenv()


def _wa_link(business: dict) -> str:
    agency_whatsapp = os.getenv("AGENCY_WHATSAPP", "")
    if not agency_whatsapp:
        return ""
    name = (business.get("name") or "your business").replace(" ", "%20")
    msg = f"Hi%2C%20I%20just%20saw%20the%20demo%20site%20you%20built%20for%20{name}"
    return f"https://wa.me/{agency_whatsapp}?text={msg}"


_TEMPLATE = """
<!-- LEADFLOW CONVERSION LAYER WITH CONTROL PANEL -->
<style>
  /* Styling for the sticky CTA bar */
  .lf-cta-bar{position:fixed;left:0;right:0;bottom:0;z-index:9998;
    display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;
    padding:14px 20px;background:rgba(10,10,12,.92);backdrop-filter:blur(12px);
    border-top:1px solid rgba(255,255,255,.12);
    transform:translateY(120%);transition:transform .45s cubic-bezier(.2,.8,.2,1);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#fff}
  .lf-cta-bar.show{transform:translateY(0)}
  .lf-cta-bar p{margin:0;font-size:15px;font-weight:500}
  .lf-cta-bar p b{color:#4d9fff}
  
  .lf-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:none;cursor:pointer;
    text-decoration:none;font-size:14px;font-weight:700;padding:10px 20px;border-radius:999px;
    transition:transform .15s,box-shadow .15s;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
  .lf-btn:hover{transform:translateY(-2px)}
  .lf-btn-primary{background:linear-gradient(135deg,#4d9fff,#2563eb);color:#fff;
    box-shadow:0 4px 15px rgba(77,159,255,.3)}
  .lf-btn-ghost{background:rgba(255,255,255,.05);color:#fff;border:1px solid rgba(255,255,255,.12)}
  .lf-btn-ghost:hover{background:rgba(255,255,255,.1)}

  /* Original Modal styles */
  .lf-modal-bg{position:fixed;inset:0;z-index:99999;display:none;align-items:center;justify-content:center;
    background:rgba(0,0,0,.72);backdrop-filter:blur(6px);padding:20px;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
  .lf-modal-bg.show{display:flex;animation:lf-fade .3s ease}
  .lf-modal{position:relative;max-width:440px;width:100%;background:#0d0e12;color:#fff;
    border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:32px 28px;text-align:center;
    box-shadow:0 30px 80px rgba(0,0,0,.6);animation:lf-pop .35s cubic-bezier(.2,.9,.3,1.2)}
  .lf-modal h2{margin:0 0 12px;font-size:24px;line-height:1.25}
  .lf-modal h2 b{color:#4d9fff}
  .lf-modal p{margin:0 0 24px;font-size:15px;line-height:1.6;color:#a0aec0}
  .lf-modal .lf-btn{width:100%;font-size:16px;padding:14px}
  .lf-modal .lf-sub{margin-top:14px;font-size:12px;color:#718096}
  .lf-x{position:absolute;top:14px;right:16px;background:none;border:none;color:#718096;
    font-size:24px;line-height:1;cursor:pointer}
  .lf-x:hover{color:#fff}

  /* Control Panel Toggle Launcher Button */
  .lf-launcher{position:fixed;bottom:30px;left:30px;width:56px;height:56px;border-radius:50%;
    background:linear-gradient(135deg,#3b82f6,#1d4ed8);border:1px solid rgba(255,255,255,0.25);
    display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:99990;
    box-shadow:0 8px 32px rgba(37, 99, 235, 0.45);transition:all 0.3s cubic-bezier(0.2,0.8,0.2,1);
    color:#fff;font-size:22px;animation:lf-pulse 2s infinite}
  .lf-launcher:hover{transform:scale(1.1) rotate(15deg);box-shadow:0 12px 40px rgba(37, 99, 235, 0.6)}
  .lf-launcher.open{transform:scale(0.9) rotate(-90deg);background:#1a202c;border-color:rgba(255,255,255,0.1)}
  .lf-launcher.shift{bottom:90px}
  
  @keyframes lf-pulse{
    0%{box-shadow:0 0 0 0 rgba(37,99,235,0.6)}
    70%{box-shadow:0 0 0 14px rgba(37,99,235,0)}
    100%{box-shadow:0 0 0 0 rgba(37,99,235,0)}
  }

  /* Control Panel Sidebar Drawer */
  .lf-drawer{position:fixed;top:0;left:-380px;width:350px;height:100vh;z-index:99995;
    background:rgba(10,11,15,0.92);backdrop-filter:blur(25px);-webkit-backdrop-filter:blur(25px);
    border-right:1px solid rgba(255,255,255,0.08);box-shadow:20px 0 80px rgba(0,0,0,0.65);
    transition:transform 0.45s cubic-bezier(0.16,1,0.3,1);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#fff;
    display:flex;flex-direction:column}
  .lf-drawer.open{transform:translateX(380px)}
  
  .lf-drawer-header{padding:28px 24px 20px;border-bottom:1px solid rgba(255,255,255,0.06);position:relative}
  .lf-badge{display:inline-block;font-size:10px;font-weight:800;letter-spacing:0.1em;
    background:rgba(59,130,246,0.12);color:#3b82f6;padding:4px 10px;border-radius:4px;
    border:1px solid rgba(59,130,246,0.25);margin-bottom:12px;text-transform:uppercase}
  .lf-drawer-header h3{margin:0;font-size:20px;font-weight:700}
  .lf-drawer-header p{margin:4px 0 0;font-size:13px;color:#a0aec0}
  
  .lf-drawer-body{padding:24px;overflow-y:auto;flex-grow:1;display:flex;flex-direction:column;gap:24px}
  .lf-section-title{font-size:12px;font-weight:700;color:#718096;text-transform:uppercase;
    letter-spacing:0.08em;margin-bottom:12px}
  
  /* Audit Card */
  .lf-audit-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
    border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:14px}
  .lf-progress-bg{height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;margin-top:6px}
  .lf-progress-bar{height:100%;border-radius:3px;transition:width 1s ease}

  /* Customizer Card */
  .lf-color-grid{display:flex;gap:10px;margin-top:8px}
  .lf-color-btn{width:34px;height:34px;border-radius:50%;border:2px solid transparent;
    cursor:pointer;transition:transform 0.2s,border-color 0.2s;position:relative}
  .lf-color-btn:hover{transform:scale(1.15)}
  .lf-color-btn.active{border-color:#fff;box-shadow:0 0 10px rgba(255,255,255,0.3)}
  .lf-color-tooltip{position:absolute;bottom:42px;left:50%;transform:translateX(-50%) translateY(5px);
    background:#1a202c;color:#fff;font-size:10px;padding:4px 8px;border-radius:4px;white-space:nowrap;
    opacity:0;pointer-events:none;transition:opacity 0.2s,transform 0.2s;box-shadow:0 4px 10px rgba(0,0,0,0.3)}
  .lf-color-btn:hover .lf-color-tooltip{opacity:1;transform:translateX(-50%) translateY(0)}

  /* Feature list */
  .lf-feat-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:10px}
  .lf-feat-item{font-size:13px;color:#cbd5e0;display:flex;align-items:center;gap:10px}
  .lf-feat-icon{color:#10b981;font-size:14px}

  /* Profile Card */
  .lf-profile{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,0.02);
    border:1px solid rgba(255,255,255,0.05);border-radius:12px;padding:12px}
  .lf-avatar{width:40px;height:40px;border-radius:50%;background:#3b82f6;display:flex;
    align-items:center;justify-content:center;font-size:18px;font-weight:700}
  .lf-profile-info{display:flex;flex-direction:column}
  .lf-profile-name{font-size:13px;font-weight:700;color:#fff}
  .lf-profile-role{font-size:11px;color:#718096}

  .lf-drawer-footer{padding:20px;border-top:1px solid rgba(255,255,255,0.06);
    display:flex;flex-direction:column;gap:10px}
  .lf-drawer-footer .lf-btn{width:100%;font-size:15px;padding:12px;font-weight:700}
  
  /* Chatbot styles */
  .lf-chat-launcher{position:fixed;bottom:30px;right:30px;width:56px;height:56px;border-radius:50%;
    background:linear-gradient(135deg,#10b981,#059669);border:1px solid rgba(255,255,255,0.25);
    display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:99990;
    box-shadow:0 8px 32px rgba(16,185,129,0.45);transition:all 0.3s cubic-bezier(0.2,0.8,0.2,1);
    color:#fff;font-size:22px;user-select:none}
  .lf-chat-launcher:hover{transform:scale(1.1);box-shadow:0 12px 40px rgba(16,185,129,0.6)}
  
  .lf-chat-window{position:fixed;bottom:96px;right:30px;width:320px;height:420px;z-index:99995;
    background:rgba(10,11,15,0.96);backdrop-filter:blur(25px);-webkit-backdrop-filter:blur(25px);
    border:1px solid rgba(255,255,255,0.08);border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,0.65);
    display:none;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#fff;
    overflow:hidden;transition:all 0.3s ease}
  .lf-chat-window.open{display:flex}
  
  .lf-chat-header{padding:14px 16px;background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.06);
    display:flex;justify-content:space-between;align-items:center}
  .lf-chat-header h4{margin:0;font-size:14px;font-weight:700;display:flex;align-items:center;gap:6px}
  .lf-chat-header h4::before{content:'';display:block;width:8px;height:8px;border-radius:50%;background:#10b981;box-shadow:0 0 6px #10b981}
  
  .lf-chat-messages{flex-grow:1;padding:16px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;
    font-size:12.5px;line-height:1.45}
  
  .lf-msg{max-width:82%;padding:8px 12px;border-radius:12px;margin-bottom:2px;word-break:break-word}
  .lf-msg-user{align-self:flex-end;background:#2563eb;color:#fff;border-bottom-right-radius:2px}
  .lf-msg-ai{align-self:flex-start;background:rgba(255,255,255,0.06);color:#e2e8f0;border-bottom-left-radius:2px;border:1px solid rgba(255,255,255,0.04)}
  
  .lf-chat-input-area{padding:10px;background:rgba(0,0,0,0.2);border-top:1px solid rgba(255,255,255,0.06);
    display:flex;gap:8px;align-items:center}
  .lf-chat-input{flex-grow:1;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
    border-radius:999px;padding:6px 14px;color:#fff;font-size:12.5px;outline:none;transition:border-color 0.2s}
  .lf-chat-input:focus{border-color:#10b981}
  .lf-chat-send{background:#10b981;border:none;color:#fff;border-radius:50%;width:28px;height:28px;
    display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:11px;transition:background 0.2s}
  .lf-chat-send:hover{background:#059669}
  
  .lf-typing{display:none;align-self:flex-start;background:rgba(255,255,255,0.03);padding:6px 12px;border-radius:12px;font-size:11px;color:#718096;margin:0 16px 8px}
  
  /* Timeline styles for Sequence */
  .lf-timeline{display:flex;flex-direction:column;gap:14px;position:relative;padding-left:14px;margin-top:10px}
  .lf-timeline::before{content:'';position:absolute;left:4px;top:6px;bottom:6px;width:1px;background:rgba(255,255,255,0.08)}
  .lf-timeline-item{display:flex;gap:10px;position:relative}
  .lf-timeline-badge{width:8px;height:8px;border-radius:50%;background:#3b82f6;margin-top:4px;
    position:absolute;left:-14px;border:2px solid #0a0b0f}
  .lf-timeline-content h4{margin:0;font-size:12.5px;font-weight:700;color:#fff}
  .lf-timeline-content p{margin:2px 0 0;font-size:10.5px;color:#718096;line-height:1.4}
  
  @keyframes lf-fade{from{opacity:0}to{opacity:1}}
</style>

<div class="lf-launcher" id="lfLauncher" aria-label="Toggle Customizer">🛠️</div>

<div class="lf-drawer" id="lfDrawer">
  <div class="lf-drawer-header">
    <div class="lf-badge">Live Demo Controls</div>
    <h3>Custom Presentation</h3>
    <p>Prepared for <b>__NAME__</b></p>
  </div>
  
  <div class="lf-drawer-body">
    <!-- Audit Section -->
    <div>
      <div class="lf-section-title">Speed & Performance Audit</div>
      <div class="lf-audit-card">
        <div>
          <div style="display:flex;justify-content:space-between;font-size:12px;color:#a0aec0">
            <span>Your Current Website:</span>
            <span style="font-weight:700;color:__SCORE_COLOR__">__SCORE_TEXT__</span>
          </div>
          <div class="lf-progress-bg">
            <div class="lf-progress-bar" style="width:__SCORE_PCT__%;background:__SCORE_COLOR__"></div>
          </div>
        </div>
        <div>
          <div style="display:flex;justify-content:space-between;font-size:12px;color:#a0aec0">
            <span>LeadFlow Modern Demo:</span>
            <span style="font-weight:700;color:#10b981">98 / 100</span>
          </div>
          <div class="lf-progress-bg">
            <div class="lf-progress-bar" style="width:98%;background:#10b981;box-shadow:0 0 8px rgba(16,185,129,0.4)"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Theme Selection -->
    <div>
      <div class="lf-section-title">Tailor Brand Colors</div>
      <p style="font-size:12px;color:#a0aec0;margin:0 0 10px">Preview this template in other primary branding styles instantly:</p>
      <div class="lf-color-grid">
        <button class="lf-color-btn active" id="lf-color-orange" data-color="orange" style="background:#E05A26" aria-label="Orange">
          <span class="lf-color-tooltip">Amber Orange</span>
        </button>
        <button class="lf-color-btn" id="lf-color-blue" data-color="blue" style="background:#2563eb" aria-label="Blue">
          <span class="lf-color-tooltip">Electric Blue</span>
        </button>
        <button class="lf-color-btn" id="lf-color-green" data-color="green" style="background:#10b981" aria-label="Green">
          <span class="lf-color-tooltip">Emerald Green</span>
        </button>
        <button class="lf-color-btn" id="lf-color-gold" data-color="gold" style="background:#d97706" aria-label="Gold">
          <span class="lf-color-tooltip">Honey Gold</span>
        </button>
        <button class="lf-color-btn" id="lf-color-pink" data-color="pink" style="background:#db2777" aria-label="Pink">
          <span class="lf-color-tooltip">Rose Pink</span>
        </button>
      </div>
    </div>

    <!-- Features -->
    <div>
      <div class="lf-section-title">Built-in Enhancements</div>
      <ul class="lf-feat-list">
        <li class="lf-feat-item"><span class="lf-feat-icon">⚡</span> 340% faster loading speed</li>
        <li class="lf-feat-item"><span class="lf-feat-icon">📱</span> Responsive mobile-first layout</li>
        <li class="lf-feat-item"><span class="lf-feat-icon">🛠️</span> Interactive pricing & cost estimators</li>
        <li class="lf-feat-item"><span class="lf-feat-icon">🎯</span> Modern UX to capture 3x more bookings</li>
      </ul>
    </div>

    <!-- Outreach Sequence Timeline -->
    <div>
      <div class="lf-section-title">Autonomous Outreach Engine</div>
      <p style="font-size:12px;color:#a0aec0;margin:0 0 12px">How we follow up with your prospects automatically:</p>
      <div class="lf-timeline">
        <div class="lf-timeline-item">
          <div class="lf-timeline-badge" style="background:#3b82f6"></div>
          <div class="lf-timeline-content">
            <h4>Day 1: Personalized Pitch</h4>
            <p>Initial email sent with custom demo site link.</p>
          </div>
        </div>
        <div class="lf-timeline-item">
          <div class="lf-timeline-badge" style="background:#10b981"></div>
          <div class="lf-timeline-content">
            <h4>Day 3: WhatsApp Nudge</h4>
            <p>Follow-up text sent if booking is pending.</p>
          </div>
        </div>
        <div class="lf-timeline-item">
          <div class="lf-timeline-badge" style="background:#fbbf24"></div>
          <div class="lf-timeline-content">
            <h4>Day 7: Social Follow-up</h4>
            <p>Instagram DM sent to maximize response rate.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Designer profile -->
    <div style="margin-top:auto">
      <div class="lf-section-title">Created By</div>
      <div class="lf-profile">
        <div class="lf-avatar">CG</div>
        <div class="lf-profile-info">
          <span class="lf-profile-name">__AGENCY__</span>
          <span class="lf-profile-role">Web Developer & Architect</span>
        </div>
      </div>
    </div>
  </div>
  
  <div class="lf-drawer-footer">
    <a href="__BOOKING__" target="_blank" rel="noopener" class="lf-btn lf-btn-primary" data-lf="cta_book_drawer">Claim Website &rarr;</a>
    __WA_BTN__
  </div>
</div>

<div class="lf-chat-launcher" id="lfChatLauncher" aria-label="Open Chat">💬</div>

<div class="lf-chat-window" id="lfChatWindow">
  <div class="lf-chat-header">
    <h4 style="margin:0">AI Assistant</h4>
    <button class="lf-x" id="lfChatClose" style="position:static;font-size:20px;padding:0;background:none;border:none;color:#718096;cursor:pointer" aria-label="Close Chat">&times;</button>
  </div>
  <div class="lf-chat-messages" id="lfChatMessages">
    <div class="lf-msg lf-msg-ai">Hi there! I'm your AI business assistant. How can I help you today?</div>
  </div>
  <div class="lf-typing" id="lfChatTyping">AI is typing...</div>
  <div class="lf-chat-input-area">
    <input type="text" class="lf-chat-input" id="lfChatInput" placeholder="Type a message...">
    <button class="lf-chat-send" id="lfChatSend" aria-label="Send message">➔</button>
  </div>
</div>

<div class="lf-cta-bar" id="lfBar">
  <p>👀 Like this design for <b>__NAME__</b>?</p>
  <a href="__BOOKING__" target="_blank" rel="noopener" class="lf-btn lf-btn-primary" data-lf="cta_book_bar">Book a free call →</a>
  __WA_BTN__
</div>

<div class="lf-modal-bg" id="lfModal">
  <div class="lf-modal">
    <button class="lf-x" id="lfX" aria-label="Close">&times;</button>
    <h2>Want this site live for <b>__NAME__</b>?</h2>
    <p>This demo was built specifically for you. Book a free 15-minute call and
       I'll have it live on your domain — no obligation, no upfront cost.</p>
    <div style="display:flex;gap:12px;justify-content:center;margin-top:15px;flex-wrap:wrap">
      <a href="__BOOKING__" target="_blank" rel="noopener" class="lf-btn lf-btn-primary" data-lf="cta_book_modal">Claim this website →</a>
      __WA_BTN__
    </div>
    <div class="lf-sub">Built by __AGENCY__</div>
  </div>
</div>

<script>
(function(){
  var BEACON="", BID="__BID__", sent={};
  // Dynamically fetch the current server URL so beacon always works even after
  // tunnel rotation — decoupled from the URL that was baked in at deploy-time.
  (function loadBeacon(){
    try{
      fetch("https://power7t.github.io/leadflow-demos/beacon-config.json?_="+Date.now(),{cache:"no-store"})
        .then(function(r){return r.json();})
        .then(function(d){BEACON=d.url||"";})
        .catch(function(){});
    }catch(e){}
  })();
  function ping(ev){
    if(sent[ev])return; sent[ev]=true;
    function _do(){if(!BEACON)return;try{fetch(BEACON+"/api/engage?bid="+BID+"&ev="+ev,{mode:"no-cors",keepalive:true});}catch(e){}}
    if(BEACON){_do();}else{setTimeout(_do,2500);} // wait for beacon config fetch
  }
  
  // Customizer color switching
  var colors = {
    orange: { primary: '#E05A26', bright: '#FF6B35', glow: 'rgba(224,90,38,0.15)' },
    blue: { primary: '#2563eb', bright: '#3b82f6', glow: 'rgba(37,99,235,0.15)' },
    green: { primary: '#10b981', bright: '#34d399', glow: 'rgba(16,185,129,0.15)' },
    gold: { primary: '#d97706', bright: '#fbbf24', glow: 'rgba(217,119,6,0.15)' },
    pink: { primary: '#db2777', bright: '#f472b6', glow: 'rgba(219,39,119,0.15)' }
  };
  
  function setAccent(key) {
    var root = document.documentElement;
    var p = colors[key];
    if (!p) return;
    
    // Standard variables across templates
    root.style.setProperty('--accent-orange', p.primary);
    root.style.setProperty('--accent-orange-bright', p.bright);
    root.style.setProperty('--accent-orange-glow', p.glow);
    root.style.setProperty('--accent-cyan', p.primary);
    root.style.setProperty('--accent-cyan-bright', p.bright);
    root.style.setProperty('--accent-cyan-glow', p.glow);
    root.style.setProperty('--accent-teal', p.primary);
    root.style.setProperty('--accent-teal-glow', p.glow);
    root.style.setProperty('--accent-gold', p.primary);
    root.style.setProperty('--accent-gold-glow', p.glow);
    root.style.setProperty('--accent-pink', p.primary);
    root.style.setProperty('--accent-pink-glow', p.glow);
    root.style.setProperty('--accent-wood', p.primary);
    root.style.setProperty('--accent-wood-glow', p.glow);
    root.style.setProperty('--accent-green', p.primary);
    root.style.setProperty('--accent-green-glow', p.glow);
    
    document.querySelectorAll('.lf-color-btn').forEach(function(btn) {
      btn.classList.remove('active');
    });
    var activeBtn = document.getElementById('lf-color-' + key);
    if (activeBtn) activeBtn.classList.add('active');
    
    ping('customize_color_' + key);
  }
  
  document.querySelectorAll('.lf-color-btn').forEach(function(btn){
    btn.addEventListener('click', function(){
      var col = btn.getAttribute('data-color');
      setAccent(col);
    });
  });

  // Drawer toggling
  var launcher = document.getElementById('lfLauncher');
  var drawer = document.getElementById('lfDrawer');
  
  launcher.addEventListener('click', function(){
    var isOpen = drawer.classList.contains('open');
    if(isOpen) {
      drawer.classList.remove('open');
      launcher.classList.remove('open');
      launcher.classList.remove('lf-panel-open');
      launcher.innerHTML = '🛠️';
      ping('drawer_closed');
    } else {
      drawer.classList.add('open');
      launcher.classList.add('open');
      launcher.classList.add('lf-panel-open');
      launcher.innerHTML = '×';
      ping('drawer_opened');
    }
  });

  // Sticky CTA bar appears once they've scrolled in a bit
  var bar=document.getElementById("lfBar"), barShown=false;
  function onScroll(){
    var sc=window.scrollY, h=document.body.scrollHeight-window.innerHeight;
    var pct=h>0?sc/h:0;
    if(pct>0.12&&!barShown){
      bar.classList.add("show");
      barShown=true;
      launcher.classList.add("shift");
      ping("scroll_in");
    }
    if(pct>0.9)ping("scroll_90");
  }
  window.addEventListener("scroll",onScroll,{passive:true});

  // Modal: exit-intent on desktop, timed on mobile, once per visit
  var modal=document.getElementById("lfModal"), fired=false;
  function openModal(){
    if(fired||sessionStorage.getItem("lfSeen"))return;
    fired=true; sessionStorage.setItem("lfSeen","1");
    modal.classList.add("show"); ping("modal_shown");
  }
  function closeModal(){modal.classList.remove("show");}
  document.getElementById("lfX").addEventListener("click",closeModal);
  modal.addEventListener("click",function(e){if(e.target===modal)closeModal();});
  if(matchMedia("(pointer:fine)").matches){
    document.addEventListener("mouseout",function(e){if(e.clientY<=0)openModal();});
  } else {
    setTimeout(openModal,28000);
  }
  
  // Chat window toggling
  var chatLauncher = document.getElementById('lfChatLauncher');
  var chatWindow = document.getElementById('lfChatWindow');
  var chatClose = document.getElementById('lfChatClose');
  var chatInput = document.getElementById('lfChatInput');
  var chatSend = document.getElementById('lfChatSend');
  var chatMessages = document.getElementById('lfChatMessages');
  var chatTyping = document.getElementById('lfChatTyping');
  
  if (chatLauncher) {
    chatLauncher.addEventListener('click', function(){
      var isOpen = chatWindow.classList.contains('open');
      if(isOpen) {
        chatWindow.classList.remove('open');
        ping('chat_closed');
      } else {
        chatWindow.classList.add('open');
        ping('chat_opened');
        chatInput.focus();
      }
    });
  }
  
  if (chatClose) {
    chatClose.addEventListener('click', function(){
      chatWindow.classList.remove('open');
    });
  }
  
  var chatHistory = [];
  
  function sendChatMessage() {
    var txt = chatInput.value.trim();
    if(!txt) return;
    chatInput.value = '';
    
    // Add User message
    var userDiv = document.createElement('div');
    userDiv.className = 'lf-msg lf-msg-user';
    userDiv.textContent = txt;
    chatMessages.appendChild(userDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    chatHistory.push({role: 'user', content: txt});
    ping('chat_message_sent');
    
    // Show typing
    chatTyping.style.display = 'block';
    
    // Send to server
    function _doChat(){
      if(!BEACON) {
        setTimeout(_doChat, 1000);
        return;
      }
      fetch(BEACON + "/leads/" + BID + "/chat", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: txt, history: chatHistory })
      })
      .then(function(r){ return r.json(); })
      .then(function(data){
        chatTyping.style.display = 'none';
        var aiDiv = document.createElement('div');
        aiDiv.className = 'lf-msg lf-msg-ai';
        aiDiv.textContent = data.reply || "Sorry, I'm having trouble connecting right now.";
        chatMessages.appendChild(aiDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        chatHistory.push({role: 'assistant', content: data.reply || ''});
      })
      .catch(function(){
        chatTyping.style.display = 'none';
        var aiDiv = document.createElement('div');
        aiDiv.className = 'lf-msg lf-msg-ai';
        aiDiv.textContent = "Sorry, I could not reach the server.";
        chatMessages.appendChild(aiDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      });
    }
    _doChat();
  }
  
  if (chatSend) chatSend.addEventListener('click', sendChatMessage);
  if (chatInput) {
    chatInput.addEventListener('keypress', function(e){
      if(e.key === 'Enter') sendChatMessage();
    });
  }

  // Track high-intent clicks
  document.querySelectorAll("[data-lf]").forEach(function(el){
    el.addEventListener("click",function(){ping(el.getAttribute("data-lf"));});
  });
})();
</script>
"""


def cta_block(business: dict) -> str:
    """Return the full conversion-layer HTML to inject before </body>."""
    name = (business.get("name") or "your business")
    booking_url = os.getenv("BOOKING_URL", "https://www.fiverr.com/s/e6zGy4g")
    agency_name = os.getenv("AGENCY_NAME", "Chandan Gosavi")

    wa = _wa_link(business)
    wa_btn = (
        f'<a href="{wa}" target="_blank" rel="noopener" class="lf-btn lf-btn-ghost" '
        f'data-lf="cta_whatsapp">WhatsApp</a>'
        if wa else ""
    )

    # Performance audit dynamic values
    score = business.get("website_score") or 0
    if score == 0:
        score_text = "No Website / 0"
        score_color = "#ef4444"  # Red
        score_pct = 10  # Minimum 10% for layout visibility
    elif score < 50:
        score_text = f"{score} / 100"
        score_color = "#ef4444"  # Red
        score_pct = max(score, 10)
    elif score < 85:
        score_text = f"{score} / 100"
        score_color = "#f59e0b"  # Amber
        score_pct = score
    else:
        score_text = f"{score} / 100"
        score_color = "#10b981"  # Emerald
        score_pct = score

    if business.get("pitch_type") == "leadflow_saas":
        # Override the template for SaaS demos so it talks about the CRM instead of "Custom Website"
        saas_template = _TEMPLATE.replace(
            "👀 Like this design for <b>__NAME__</b>?", "👀 Like this automation for <b>__NAME__</b>?"
        ).replace(
            "Want this site live for <b>__NAME__</b>?", "Want these tools live for <b>__NAME__</b>?"
        ).replace(
            "This demo was built specifically for you. Book a free 15-minute call and\n       I'll have it live on your domain — no obligation, no upfront cost.",
            "This CRM preview was built specifically for you. Book a free 15-minute call and\n       I'll set up your autopilot system — no obligation, no upfront cost."
        ).replace(
            "Claim this website →", "Claim this CRM →"
        ).replace(
            "Custom Presentation", "SaaS Presentation"
        ).replace(
            "Your Current Website:", "Your Current CRM:"
        ).replace(
            "LeadFlow Modern Demo:", "LeadFlow Automation:"
        )
        return (
            saas_template
            .replace("__NAME__", name)
            .replace("__BOOKING__", booking_url)
            .replace("__AGENCY__", agency_name)
            .replace("__WA_BTN__", wa_btn)
            .replace("__BEACON__", "")
            .replace("__BID__", str(business.get("id", "")))
            .replace("__SCORE_TEXT__", score_text)
            .replace("__SCORE_COLOR__", score_color)
            .replace("__SCORE_PCT__", str(score_pct))
        )

    return (
        _TEMPLATE
        .replace("__NAME__", name)
        .replace("__BOOKING__", booking_url)
        .replace("__AGENCY__", agency_name)
        .replace("__WA_BTN__", wa_btn)
        # __BEACON__ is intentionally left empty — the JS loads it dynamically
        # from beacon-config.json so tunnel rotation never breaks existing demos.
        .replace("__BEACON__", "")
        .replace("__BID__", str(business.get("id", "")))
        .replace("__SCORE_TEXT__", score_text)
        .replace("__SCORE_COLOR__", score_color)
        .replace("__SCORE_PCT__", str(score_pct))
    )
