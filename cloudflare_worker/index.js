/**
 * LeadFlow Cloudflare Worker Middleware (Always-Online Relay & Edge Renderer)
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

// LeadFlow Conversion Layer Template
const TEMPLATE = `
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
    if(BEACON){_do();}else{setTimeout(_do,2500);}
  }
  
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
    
    var userDiv = document.createElement('div');
    userDiv.className = 'lf-msg lf-msg-user';
    userDiv.textContent = txt;
    chatMessages.appendChild(userDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    chatHistory.push({role: 'user', content: txt});
    ping('chat_message_sent');
    
    chatTyping.style.display = 'block';
    
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

  document.querySelectorAll("[data-lf]").forEach(function(el){
    el.addEventListener("click",function(){ping(el.getAttribute("data-lf"));});
  });
})();
</script>
`;

function waLink(business, env) {
  const agencyWhatsapp = env.AGENCY_WHATSAPP || "";
  if (!agencyWhatsapp) return "";
  const name = encodeURIComponent(business.name || "your business");
  const msg = `Hi%2C%20I%20just%20saw%20the%20demo%20site%20you%20built%20for%20${name}`;
  return `https://wa.me/${agencyWhatsapp}?text=${msg}`;
}

function ctaBlock(business, env) {
  const name = business.name || "your business";
  const bookingUrl = env.BOOKING_URL || "https://www.fiverr.com/s/e6zGy4g";
  const agencyName = env.AGENCY_NAME || "Chandan Gosavi";

  const wa = waLink(business, env);
  const waBtn = wa
    ? `<a href="${wa}" target="_blank" rel="noopener" class="lf-btn lf-btn-ghost" data-lf="cta_whatsapp">WhatsApp</a>`
    : "";

  let score = business.website_score || 0;
  let scoreText = "";
  let scoreColor = "";
  let scorePct = 0;

  if (score === 0) {
    scoreText = "No Website / 0";
    scoreColor = "#ef4444";
    scorePct = 10;
  } else if (score < 50) {
    scoreText = `${score} / 100`;
    scoreColor = "#ef4444";
    scorePct = Math.max(score, 10);
  } else if (score < 85) {
    scoreText = `${score} / 100`;
    scoreColor = "#f59e0b";
    scorePct = score;
  } else {
    scoreText = `${score} / 100`;
    scoreColor = "#10b981";
    scorePct = score;
  }

  let template = TEMPLATE;

  if (business.pitch_type === "leadflow_saas") {
    template = template
      .replace(/👀 Like this design for <b>__NAME__<\/b>\?/g, "👀 Like this automation for <b>__NAME__</b>?")
      .replace(/Want this site live for <b>__NAME__<\/b>\?/g, "Want these tools live for <b>__NAME__</b>?")
      .replace(
        /This demo was built specifically for you\. Book a free 15-minute call and\n       I'll have it live on your domain — no obligation, no upfront cost\./g,
        "This CRM preview was built specifically for you. Book a free 15-minute call and\n       I'll set up your autopilot system — no obligation, no upfront cost."
      )
      .replace(/Claim this website →/g, "Claim this CRM →")
      .replace(/Custom Presentation/g, "SaaS Presentation")
      .replace(/Your Current Website:/g, "Your Current CRM:")
      .replace(/LeadFlow Modern Demo:/g, "LeadFlow Automation:");
  }

  return template
    .replace(/__NAME__/g, name)
    .replace(/__BOOKING__/g, bookingUrl)
    .replace(/__AGENCY__/g, agencyName)
    .replace(/__WA_BTN__/g, waBtn)
    .replace(/__BEACON__/g, "")
    .replace(/__BID__/g, String(business.id || ""))
    .replace(/__SCORE_TEXT__/g, scoreText)
    .replace(/__SCORE_COLOR__/g, scoreColor)
    .replace(/__SCORE_PCT__/g, String(scorePct));
}

// Lightweight sandboxed Jinja/Nunjucks interpreter
function getValue(path, context) {
  const parts = path.split(/\s+or\s+/);
  const primaryPath = parts[0].trim();
  const fallbackVal = parts[1] ? parts[1].trim().replace(/['"]/g, "") : "";

  const keys = primaryPath.split('.');
  let val = context;
  for (const k of keys) {
    if (val === null || val === undefined) break;
    val = val[k];
  }

  return (val !== null && val !== undefined && val !== "") ? val : fallbackVal;
}

function interpretVariables(html, context) {
  const varRegex = /\{\{\s*(.*?)\s*\}\}/g;
  return html.replace(varRegex, (match, path) => {
    return getValue(path, context);
  });
}

function interpretTemplate(html, context) {
  let result = html;
  
  // 1. Handle loops: {% for item in list %}...{% endfor %}
  const forRegex = /\{%\s*for\s+(\w+)\s+in\s+([\w\.]+)\s*%\}([\s\S]*?)\{%\s*endfor\s*%\}/g;
  result = result.replace(forRegex, (match, itemVar, listPath, body) => {
    const list = getValue(listPath, context);
    if (!Array.isArray(list) || list.length === 0) {
      return "";
    }
    return list.map(item => {
      const localContext = { ...context, [itemVar]: item };
      return interpretVariables(body, localContext);
    }).join("");
  });

  // 2. Handle conditionals: {% if condition %}...{% endif %}
  const ifRegex = /\{%\s*if\s+(.*?)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}/g;
  let lastResult;
  do {
    lastResult = result;
    result = result.replace(ifRegex, (match, condition, body) => {
      let isTrue = false;
      
      if (condition.includes(" and ")) {
        const parts = condition.split(" and ");
        isTrue = parts.every(part => !!getValue(part.trim(), context));
      } else if (condition.includes(" or ")) {
        const parts = condition.split(" or ");
        isTrue = parts.some(part => !!getValue(part.trim(), context));
      } else {
        isTrue = !!getValue(condition.trim(), context);
      }
      
      let trueBody = body;
      let falseBody = "";
      const elseIndex = body.indexOf("{% else %}");
      if (elseIndex !== -1) {
        trueBody = body.substring(0, elseIndex);
        falseBody = body.substring(elseIndex + 10);
      }
      
      return isTrue ? trueBody : falseBody;
    });
  } while (result !== lastResult);

  // 3. Variable substitution
  return interpretVariables(result, context);
}

async function notifyNtfy(message, env, title = "LeadFlow Edge") {
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

async function notifyAll(message, env, title = "LeadFlow Edge") {
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

    // ── Template Upload API ─────────────────────────────────────────────────────
    if (url.pathname === "/api/template") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }

      const id = url.searchParams.get("id");
      if (!id) {
        return new Response("Missing template id", { status: 400 });
      }

      const content = await request.text();
      await env.LEADFLOW_KV.put(`demo:template:${id}`, content);

      return new Response(JSON.stringify({ success: true, message: `Template ${id} uploaded` }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      });
    }

    // ── Demo Data Upload API ─────────────────────────────────────────────────────
    if (url.pathname === "/api/demo") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }

      const slug = url.searchParams.get("slug");
      if (!slug) {
        return new Response("Missing slug", { status: 400 });
      }

      const payload = await request.json();
      await env.LEADFLOW_KV.put(`demo:data:${slug}`, JSON.stringify(payload));

      return new Response(JSON.stringify({ success: true, message: `Demo data for ${slug} saved` }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      });
    }

    // ── Demo Rendering Route (GET /demo/:slug) ──────────────────────────────────
    if (url.pathname.startsWith("/demo/")) {
      let slug = url.pathname.substring(6); // remove "/demo/"
      if (!slug) {
        return new Response("Missing Slug", { status: 400 });
      }

      // If the URL is pretty (e.g., "the-garage-chicago-gym-99"), extract the ID from the end
      let lookupKey = slug;
      if (slug.includes('-')) {
         const parts = slug.split('-');
         const lastPart = parts[parts.length - 1];
         if (!isNaN(lastPart)) {
             lookupKey = lastPart;
         }
      }

      let rawData = await env.LEADFLOW_KV.get(`demo:data:${lookupKey}`);
      // Fallback in case they used the exact slug
      if (!rawData) {
          rawData = await env.LEADFLOW_KV.get(`demo:data:${slug}`);
      }
      
      if (!rawData) {
        return new Response("Demo Not Found", { status: 404 });
      }

      let payload;
      try {
        payload = JSON.parse(rawData);
      } catch (e) {
        return new Response("Error parsing demo data", { status: 500 });
      }

      const templateId = payload.template_id || "example.html";
      const templateContent = await env.LEADFLOW_KV.get(`demo:template:${templateId}`);
      if (!templateContent) {
        return new Response(`Template ${templateId} Not Found`, { status: 404 });
      }

      // Check if it's a real user or a link preview bot (Telegram/IG/WA)
      const utm = url.searchParams.get("utm");
      if (utm === "ig" || utm === "wa") {
         const ua = (request.headers.get("user-agent") || "").toLowerCase();
         const isBot = ua.includes("bot") || ua.includes("telegram") || ua.includes("instagram") || ua.includes("facebook") || ua.includes("whatsapp") || ua.includes("preview") || ua.includes("crawler") || ua.includes("spider") || ua.includes("slurp");
         
         if (!isBot) {
            const bizName = payload.business?.name || "A business";
            const icon = utm === "wa" ? "📱" : "📸";
            await notifyNtfy(`${icon} ${utm.toUpperCase()} Prospect Clicked: ${bizName} just opened their custom demo!`, env, `Leadflow ${utm.toUpperCase()} Click`);
         }
      }

      try {
        // Compile template using our custom lightweight interpreter
        let rendered = interpretTemplate(templateContent, {
          lead: payload.business,
          scraped: payload.website_data,
          hero_img: payload.hero_img,
          about_img: payload.about_img
        });

        // Append conversion layer
        const ctaHtml = ctaBlock(payload.business, env);
        const trackingHtml = `
<!-- TRACKING SCRIPT -->
<script>
  try { fetch("/api/track.png?bid=${payload.business.id}", {mode:"no-cors"}); } catch(e) {}
</script>
`;
        const extra = ctaHtml + "\n" + trackingHtml;
        let finalHtml = rendered;

        if (rendered.includes("</body>")) {
          finalHtml = rendered.replace("</body>", extra + "\n</body>");
        } else {
          finalHtml = rendered + extra;
        }

        return new Response(finalHtml, {
          headers: { "Content-Type": "text/html; charset=utf-8", "Access-Control-Allow-Origin": "*" }
        });
      } catch (e) {
        return new Response(`Rendering Error: ${e.message}`, { status: 500 });
      }
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

    // ── Leadership Lease API for Bidirectional Dynamic Failover ────────────────
    if (url.pathname === "/api/leadership") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      const currentLeader = await env.LEADFLOW_KV.get("leadership:current_leader") || "";
      const heartbeatMac = await env.LEADFLOW_KV.get("heartbeat:mac") || "0";
      const heartbeatFirestick = await env.LEADFLOW_KV.get("heartbeat:firestick") || "0";

      return new Response(JSON.stringify({
        current_leader: currentLeader,
        heartbeats: {
          mac: parseInt(heartbeatMac),
          firestick: parseInt(heartbeatFirestick)
        }
      }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      });
    }

    if (url.pathname === "/api/leadership/claim") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;

      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }

      const device = url.searchParams.get("device"); // 'mac' or 'firestick'
      if (!device || (device !== "mac" && device !== "firestick")) {
        return new Response("Invalid Device", { status: 400 });
      }

      const now = Date.now();
      const currentLeader = await env.LEADFLOW_KV.get("leadership:current_leader") || "";
      
      // Update this device's heartbeat regardless of leader status so it shows as online
      await env.LEADFLOW_KV.put(`heartbeat:${device}`, String(now));

      let leaderActive = false;
      if (currentLeader) {
        const leaderHeartbeat = await env.LEADFLOW_KV.get(`heartbeat:${currentLeader}`) || "0";
        const ageMs = now - parseInt(leaderHeartbeat);
        // Leader is active if heartbeat is less than 10 minutes (600,000 ms) old
        if (ageMs < 600000) {
          leaderActive = true;
        }
      }

      // Preemption: Firestick (Primary) can preempt Mac (Backup) instantly
      const isPreemption = (device === "firestick" && currentLeader === "mac");

      if (leaderActive && currentLeader !== device && !isPreemption) {
        // Current leader is active and is not this device, claim rejected
        return new Response(JSON.stringify({ success: false, current_leader: currentLeader, message: "Another active leader exists" }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
      }

      // Claim leadership (or renew lease)
      await env.LEADFLOW_KV.put("leadership:current_leader", device);

      return new Response(JSON.stringify({ success: true, current_leader: device, message: "Leadership claimed/renewed successfully" }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      });
    }

    // ── Generic KV Write API (/api/kv) ─────────────────────────────────────────
    // Used by scheduler to push bot:stats, bot:drafts etc. to KV
    if (url.pathname === "/api/kv" && method === "POST") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      const configuredToken = env.SECRET_TOKEN || SECRET_TOKEN;
      if (headerToken !== configuredToken) {
        return new Response("Unauthorized", { status: 401 });
      }
      const body = await request.json().catch(() => ({}));
      const { key, value } = body;
      if (!key || value === undefined) {
        return new Response(JSON.stringify({ error: "key and value required" }), { status: 400, headers: { "Content-Type": "application/json" } });
      }
      await env.LEADFLOW_KV.put(key, typeof value === "string" ? value : JSON.stringify(value));
      return new Response(JSON.stringify({ ok: true, key }), { headers: { "Content-Type": "application/json" } });
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

    // ── 5. Telegram Bot Webhook (/bot/webhook) ───────────────────────────────────
    // Set the webhook once with:
    //   curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://leadflow-relay.chandango12.workers.dev/bot/webhook"
    if (url.pathname === "/bot/webhook" && method === "POST") {
      const BOT_TOKEN = env.TELEGRAM_BOT_TOKEN;
      const ALLOWED_USER = parseInt(env.TELEGRAM_USER_ID || "0", 10);

      if (!BOT_TOKEN || !ALLOWED_USER) {
        return new Response("Bot not configured", { status: 503 });
      }

      async function tgSend(method, payload) {
        const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        return r.json();
      }

      async function sendMenu(chatId, editMsgId = null) {
        const statsRaw = await env.LEADFLOW_KV.get("bot:stats");
        const stats = statsRaw ? JSON.parse(statsRaw) : {};
        const autopilot = stats.autopilot_active ? "🟢 ACTIVE" : "🔴 STOPPED";
        const text = `⚡️ *LEADFLOW™ ADVANCED CONSOLE*\n━━━━━━━━━━━━━━━━━━\n🟢 *Status:* System Operational\n🤖 *Autopilot:* ${autopilot}\n📡 *Relay:* Cloudflare Edge\n\nSelect an option:`;
        const reply_markup = { inline_keyboard: [
          [{ text: "📊 Stats", callback_data: "stats" }, { text: "🚀 Autopilot", callback_data: "trigger" }],
          [{ text: "📝 Pending Drafts", callback_data: "drafts" }, { text: "⚙️ System Status", callback_data: "status" }],
          [{ text: "📸 IG DM Mode", callback_data: "ig_dm_0" }, { text: "📱 WA Mode", callback_data: "wa_dm_0" }]
        ]};
        if (editMsgId) {
          return tgSend("editMessageText", { chat_id: chatId, message_id: editMsgId, text, parse_mode: "Markdown", reply_markup });
        }
        return tgSend("sendMessage", { chat_id: chatId, text, parse_mode: "Markdown", reply_markup });
      }


      const IG_DM_TEMPLATES = {
        medspa:        "Hey {{name}}. Came across {{biz}} and love your page. I build digital infrastructure for medspas and put together a custom mockup for you. It's designed specifically to convert your profile traffic into high-ticket bookings. View it here:\n{{demo}}",
        interiordesign:"Hey {{name}}. Love the portfolio at {{biz}}. I build conversion systems for interior designers and put together a custom mockup for you. It's built to capture more high-value project leads. You can view it here:\n{{demo}}",
        orthodontist:  "Hey {{name}}. Came across {{biz}}—great practice. I build lead-gen infrastructure for orthodontists and put together a custom mockup for you. It's optimized to drive more consultation requests. View it here:\n{{demo}}",
        dentist:       "Hey {{name}}. Came across {{biz}} and love what you're doing. I build conversion systems for dental clinics and put together a custom mockup for you. It's designed to bring in more high-ticket patients. Check it out:\n{{demo}}",
        gym:           "Hey {{name}}. Came across {{biz}}—great facility. I build digital infrastructure for fitness studios and put together a custom mockup for you. It's built specifically to capture leads and drive trial memberships. View it here:\n{{demo}}",
        restaurant:    "Hey {{name}}. Love what you're doing at {{biz}}. I build conversion-focused sites for hospitality and put together a custom mockup for you. It's designed to streamline reservations and online orders. Check it out:\n{{demo}}",
        barbershop:    "Hey {{name}}. Came across {{biz}} and love the aesthetic. I build digital infrastructure for premium shops and put together a custom mockup for you. It's designed to drive more walk-ins and bookings. View it here:\n{{demo}}",
        realestate:    "Hey {{name}}. Came across {{biz}}—great listings. I build conversion infrastructure for top agents and put together a custom mockup for you. It's designed specifically to capture buyer/seller leads. You can view it here:\n{{demo}}",
        lawyer:        "Hey {{name}}. Came across {{biz}} and respect your practice. I build digital infrastructure for law firms and put together a custom mockup for you. It's designed to build trust and capture more consultation leads. View it here:\n{{demo}}",
        accountant:    "Hey {{name}}. Came across {{biz}}. I build conversion systems for accounting firms and put together a custom mockup for you. It's designed to capture more high-value B2B leads. View it here:\n{{demo}}",
        detailing:     "Hey {{name}}. Came across {{biz}} and love your work. I build digital infrastructure for premium detailers and put together a custom mockup for you. It's built to drive more high-ticket bookings. Check it out:\n{{demo}}",
        remodeler:     "Hey {{name}}. Love the projects at {{biz}}. I build conversion systems for remodelers and put together a custom mockup for you. It's designed to capture more qualified quote requests. View it here:\n{{demo}}",
        flooring:      "Hey {{name}}. Came across {{biz}}. I build digital infrastructure for contractors and put together a custom mockup for you. It's designed to showcase your work and capture quote requests. View it here:\n{{demo}}",
        solar:         "Hey {{name}}. Came across {{biz}}—great work. I build conversion systems for solar companies and put together a custom mockup for you. It's optimized to capture exclusive consultation leads. View it here:\n{{demo}}",
        roofing:       "Hey {{name}}. Came across {{biz}}. I build digital infrastructure for roofers and put together a custom mockup for you. It's designed to capture more high-ticket quote requests. Check it out:\n{{demo}}",
        chiropractor:  "Hey {{name}}. Came across {{biz}}—great practice. I build conversion systems for chiropractors and put together a custom mockup for you. It's designed to drive more new patient bookings. View it here:\n{{demo}}",
        default:       "Hey {{name}}. Came across {{biz}} and love what you're doing. I build conversion-focused websites and put together a custom mockup for you. It's designed specifically to capture more leads for your business. View it here:\n{{demo}}"
      };

      const IG_PRICING = {
        medspa:        "$800 – $2,000 + $149/mo",
        interiordesign:"$800 – $2,000 + $149/mo",
        orthodontist:  "$1,000 – $2,500 + $199/mo",
        dentist:       "$800 – $2,000 + $149/mo",
        gym:           "$500 – $1,200 + $99/mo",
        restaurant:    "$400 – $900 + $79/mo",
        barbershop:    "$300 – $700 + $59/mo",
        realestate:    "$500 – $1,500 + $99/mo",
        lawyer:        "$1,000 – $3,000 + $199/mo",
        accountant:    "$800 – $2,000 + $149/mo",
        detailing:     "$300 – $700 + $59/mo",
        remodeler:     "$500 – $1,200 + $99/mo",
        flooring:      "$400 – $900 + $79/mo",
        solar:         "$600 – $1,500 + $99/mo",
        roofing:       "$500 – $1,200 + $99/mo",
        chiropractor:  "$500 – $1,000 + $99/mo",
        default:       "$400 – $1,000 + $79/mo"
      };

      function getPricing(category) {
        const cat = (category || "").toLowerCase().replace(/\s+/g, "");
        for (const [key, val] of Object.entries(IG_PRICING)) {
          if (cat.includes(key)) return val;
        }
        return IG_PRICING.default;
      }

      function buildDmMessage(biz) {
        const cat = (biz.category || "").toLowerCase().replace(/\s+/g, "");
        let tmpl = IG_DM_TEMPLATES.default;
        for (const [key, val] of Object.entries(IG_DM_TEMPLATES)) {
          if (cat.includes(key)) { tmpl = val; break; }
        }
        
        let words = (biz.business_name || biz.name || "there").trim().split(/\s+/).filter(w => w.length > 0);
        let firstName = "there";
        if (words.length > 0) {
            let skipWords = ["the", "a", "an", "dr", "dr.", "mr", "mr.", "ms", "ms.", "mrs", "mrs."];
            let firstWord = words[0];
            if (skipWords.includes(firstWord.toLowerCase()) && words.length > 1) {
                firstName = words[1];
            } else {
                firstName = firstWord;
            }
        }
        if (firstName !== "there") {
           firstName = firstName.charAt(0).toUpperCase() + firstName.slice(1).toLowerCase();
        }

        return tmpl
          .replace(/{{name}}/g, firstName)
          .replace(/{{biz}}/g, biz.business_name || biz.name || "your business")
          .replace(/{{demo}}/g, biz.demo_url || "");
      }

      async function sendIgDm(chatId, msgId, offset = 0) {
        const leadsRaw = await env.LEADFLOW_KV.get("bot:ig_leads");
        const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
        if (!leads.length) {
          return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
            text: "📸 *No Tier 1/2 businesses available for IG DM right now.*\n\nAll done or not yet synced from Firestick.",
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] }
          });
        }

        const idx = offset % leads.length;
        const b = leads[idx];
        const tierBadge  = b.tier === 1 ? "🔥 Tier 1" : "🥈 Tier 2";
        const pricing    = getPricing(b.category);
        const bizName    = b.business_name || b.name || "";
        let igUrl = "";
        if (b.instagram_handle) {
          // If we have their exact handle, clean it up and link directly
          let handle = b.instagram_handle.replace('@', '').replace('https://instagram.com/', '').replace('https://www.instagram.com/', '').split('/')[0];
          igUrl = `https://www.instagram.com/${handle}`;
        } else {
          // Fallback to searching their business name
          igUrl = `https://www.instagram.com/explore/search/keyword/?q=${encodeURIComponent(bizName)}`;
        }
        
        // Generate a beautiful SEO-friendly link combining their name and ID
        const slugifiedName = bizName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        const demoUrl = b.demo_url || `https://leadflow-relay.chandango12.workers.dev/demo/${slugifiedName ? slugifiedName + '-' : ''}${b.business_id || b.id}`;
        const prospectDemoUrl = demoUrl.includes('?') ? `${demoUrl}&utm=ig` : `${demoUrl}?utm=ig`;
        
        let dmMsg = "";
        if (b.ai_draft && b.ai_draft.length > 10) {
          // If the AI generated a hyper-personalized draft, use it (append demo link if missing)
          dmMsg = b.ai_draft;
          if (!dmMsg.includes(demoUrl) && !dmMsg.includes(prospectDemoUrl)) {
             dmMsg += `\n\nDemo: ${prospectDemoUrl}`;
          } else {
             // Replace the clean url with the tracked url inside the AI draft
             dmMsg = dmMsg.replace(demoUrl, prospectDemoUrl);
          }
        } else {
          // Fallback to professional static template
          dmMsg = buildDmMessage({ ...b, demo_url: prospectDemoUrl });
        }

        // Card — pricing at top, DM in code block (long-press to copy on mobile)
        const text = (
          `📸 <b>IG DM OUTREACH — ${idx+1} of ${leads.length}</b>\n` +
          `━━━━━━━━━━━━━━━━━━\n` +
          `${tierBadge}  |  📂 <b>${(b.category || "").toUpperCase()}</b>\n` +
          `🏢 <b>${bizName}</b>\n` +
          `📍 ${b.city || ""}\n` +
          `📱 <b>Instagram:</b> <a href="${igUrl}">${igUrl}</a>\n\n` +
          `💰 <b>Suggested Charge:</b> <code>${pricing}</code>\n\n` +
          `━━━━━━━━━━━━━━━━━━\n` +
          `💬 <b>DM Message</b> <i>(Tap below to copy instantly)</i>:\n\n` +
          `<code>${dmMsg}</code>`
        );

        const reply_markup = { inline_keyboard: [
          // URL buttons — tap to open directly, no callback needed
          [
            { text: "🔗 View Demo",      url: demoUrl }
          ],
          [
            { text: "✅ DM Sent",  callback_data: `ig_done_${b.business_id || b.id}` },
            { text: "❌ Skip",     callback_data: `ig_skip_${b.business_id || b.id}` },
            { text: "⏭️ Next",    callback_data: `ig_dm_${idx + 1}` }
          ],
          [
            { text: "🔄 Regenerate", callback_data: `ig_regen_${b.business_id || b.id}_${idx}` },
            { text: "🔙 Main Menu", callback_data: "menu" }
          ]
        ]};


        return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
          text: text.slice(0, 4000), parse_mode: "HTML", reply_markup });
      }
      // ── End IG DM Mode ────────────────────────────────────────────────────────

      

async function sendWaDm(chatId, msgId, offset = 0) {
        const leadsRaw = await env.LEADFLOW_KV.get("bot:wa_leads");
        const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
        if (!leads.length) {
          return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
            text: "📸 *No Tier 1/2 businesses available for WA Mode right now.*\n\nAll done or not yet synced from Firestick.",
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] }
          });
        }

        const idx = offset % leads.length;
        const b = leads[idx];
        const tierBadge  = b.tier === 1 ? "🔥 Tier 1" : "🥈 Tier 2";
        const pricing    = getPricing(b.category);
        const bizName    = b.business_name || b.name || "";
        let igUrl = "";
        if (b.instagram_handle) {
          // If we have their exact handle, clean it up and link directly
          let handle = b.instagram_handle.replace('@', '').replace('https://instagram.com/', '').replace('https://www.instagram.com/', '').split('/')[0];
          igUrl = `https://www.instagram.com/${handle}`;
        } else {
          // Fallback to searching their business name
          igUrl = `https://www.instagram.com/explore/search/keyword/?q=${encodeURIComponent(bizName)}`;
        }
        
        // Generate a beautiful SEO-friendly link combining their name and ID
        const slugifiedName = bizName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        const demoUrl = b.demo_url || `https://leadflow-relay.chandango12.workers.dev/demo/${slugifiedName ? slugifiedName + '-' : ''}${b.business_id || b.id}`;
        const prospectDemoUrl = demoUrl.includes('?') ? `${demoUrl}&utm=ig` : `${demoUrl}?utm=ig`;
        
        let dmMsg = "";
        if (b.ai_draft && b.ai_draft.length > 10) {
          // If the AI generated a hyper-personalized draft, use it (append demo link if missing)
          dmMsg = b.ai_draft;
          if (!dmMsg.includes(demoUrl) && !dmMsg.includes(prospectDemoUrl)) {
             dmMsg += `\n\nDemo: ${prospectDemoUrl}`;
          } else {
             // Replace the clean url with the tracked url inside the AI draft
             dmMsg = dmMsg.replace(demoUrl, prospectDemoUrl);
          }
        } else {
          // Fallback to professional static template
          dmMsg = buildDmMessage({ ...b, demo_url: prospectDemoUrl });
        }

        // Card — pricing at top, DM in code block (long-press to copy on mobile)
        const text = (
          `📸 <b>WA Mode OUTREACH — ${idx+1} of ${leads.length}</b>\n` +
          `━━━━━━━━━━━━━━━━━━\n` +
          `${tierBadge}  |  📂 <b>${(b.category || "").toUpperCase()}</b>\n` +
          `🏢 <b>${bizName}</b>\n` +
          `📍 ${b.city || ""}\n` +
          `📱 <b>Instagram:</b> <a href="${igUrl}">${igUrl}</a>\n\n` +
          `💰 <b>Suggested Charge:</b> <code>${pricing}</code>\n\n` +
          `━━━━━━━━━━━━━━━━━━\n` +
          `💬 <b>DM Message</b> <i>(Tap below to copy instantly)</i>:\n\n` +
          `<code>${dmMsg}</code>`
        );

        const reply_markup = { inline_keyboard: [
          // URL buttons — tap to open directly, no callback needed
          [
            { text: "🔗 View Demo",      url: demoUrl }
          ],
          [
            { text: "✅ WA Sent",  callback_data: `wa_done_${b.business_id || b.id}` },
            { text: "❌ Skip",     callback_data: `wa_skip_${b.business_id || b.id}` },
            { text: "⏭️ Next",    callback_data: `wa_dm_${idx + 1}` }
          ],
          [
            { text: "🔄 Regenerate", callback_data: `wa_regen_${b.business_id || b.id}_${idx}` },
            { text: "💬 Open WhatsApp", url: `https://wa.me/${(b.phone_number || b.phone || "").replace(/[^0-9]/g, '')}` }
          ],
          [{ text: "🔙 Main Menu", callback_data: "menu" }]]};


        return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
          text: text.slice(0, 4000), parse_mode: "HTML", reply_markup });
      }
      // ── End WA Mode Mode ────────────────────────────────────────────────────────

      async function sendStats(chatId, msgId) {
        const statsRaw = await env.LEADFLOW_KV.get("bot:stats");
        const s = statsRaw ? JSON.parse(statsRaw) : {};
        const text = (
          `📊 *LEADFLOW LIVE METRICS*\n━━━━━━━━━━━━━━━━━━\n` +
          `📥 *New Backlog:*  \`${(s.new||0).toLocaleString()}\` leads\n` +
          `✅ *Approved:*     \`${(s.approved||0).toLocaleString()}\` leads\n` +
          `🚀 *Sent:*         \`${(s.sent||0).toLocaleString()}\` emails\n` +
          `💬 *Replied:*      \`${(s.replied||0).toLocaleString()}\` contacts\n` +
          `⏭️ *Skipped:*      \`${(s.skipped||0).toLocaleString()}\` leads\n` +
          `💼 *Closed:*       \`${(s.closed||0).toLocaleString()}\` deals\n` +
          `🚫 *Opted Out:*    \`${(s.opted_out||0).toLocaleString()}\` leads\n\n` +
          `🤖 *Autopilot:* \`${s.autopilot_active ? 'ENABLED' : 'DISABLED'}\``
        );
        const reply_markup = { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] };
        return tgSend("editMessageText", { chat_id: chatId, message_id: msgId, text, parse_mode: "Markdown", reply_markup });
      }

      async function sendDrafts(chatId, msgId, offset = 0) {
        const draftsRaw = await env.LEADFLOW_KV.get("bot:drafts");
        const drafts = draftsRaw ? JSON.parse(draftsRaw) : [];
        if (!drafts.length) {
          return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
            text: "📝 *No pending drafts right now.*",
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] }
          });
        }
        const idx = offset % drafts.length;
        const d = drafts[idx];
        const demoUrl = `https://leadflow-relay.chandango12.workers.dev/demo/${d.slug || d.business_id}`;
        const text = (
          `📝 *DRAFT REVIEW (${idx+1}/${drafts.length})*\n━━━━━━━━━━━━━━━━━━\n` +
          `🏢 *Target:* \`${d.business_name}\` (ID: \`${d.business_id}\`)\n` +
          `📡 *Channel:* \`${(d.channel||"email").toUpperCase()}\`\n` +
          `📧 *Recipient:* \`${d.contact_email || "N/A"}\`\n` +
          `🔗 *Demo:* ${demoUrl}\n\n` +
          `📨 *Subject:* ${d.subject || "N/A"}\n\n*Body:*\n${(d.body || d.draft || "").slice(0, 800)}`
        );
        const reply_markup = { inline_keyboard: [
          [
            { text: "✅ Approve Send", callback_data: `approve_${d.draft_id}` },
            { text: "❌ Skip", callback_data: `skip_${d.business_id}` },
            { text: "⏭️ Next", callback_data: `drafts_${idx+1}` }
          ],
          [{ text: "🔙 Main Menu", callback_data: "menu" }]
        ]};
        return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
          text: text.slice(0, 4000), parse_mode: "Markdown", reply_markup });
      }

      async function handleApprove(chatId, msgId, draftId) {
        // Mark draft as approved in KV queue for Firestick to pick up
        const queueRaw = await env.LEADFLOW_KV.get("bot:send_queue") || "[]";
        const queue = JSON.parse(queueRaw);
        queue.push({ draft_id: parseInt(draftId), approved_at: new Date().toISOString() });
        await env.LEADFLOW_KV.put("bot:send_queue", JSON.stringify(queue));
        // Remove from drafts list
        const draftsRaw = await env.LEADFLOW_KV.get("bot:drafts");
        const drafts = draftsRaw ? JSON.parse(draftsRaw) : [];
        const updated = drafts.filter(d => String(d.draft_id) !== String(draftId));
        await env.LEADFLOW_KV.put("bot:drafts", JSON.stringify(updated));
        await tgSend("answerCallbackQuery", { callback_query_id: "", text: "✅ Queued for sending!" });
        return sendDrafts(chatId, msgId, 0);
      }

      async function handleSkip(chatId, msgId, bid) {
        // Mark as skipped in KV for Firestick to sync
        const skipRaw = await env.LEADFLOW_KV.get("bot:skip_queue") || "[]";
        const skipQueue = JSON.parse(skipRaw);
        skipQueue.push({ business_id: parseInt(bid), skipped_at: new Date().toISOString() });
        await env.LEADFLOW_KV.put("bot:skip_queue", JSON.stringify(skipQueue));
        // Remove from drafts
        const draftsRaw = await env.LEADFLOW_KV.get("bot:drafts");
        const drafts = draftsRaw ? JSON.parse(draftsRaw) : [];
        const updated = drafts.filter(d => String(d.business_id) !== String(bid));
        await env.LEADFLOW_KV.put("bot:drafts", JSON.stringify(updated));
        return sendDrafts(chatId, msgId, 0);
      }

      async function sendStatus(chatId, msgId) {
        const fsHb = await env.LEADFLOW_KV.get("heartbeat:firestick");
        const macHb = await env.LEADFLOW_KV.get("heartbeat:mac");
        const now = Date.now();
        const fsAge = fsHb ? Math.round((now - parseInt(fsHb)) / 1000) : null;
        const macAge = macHb ? Math.round((now - parseInt(macHb)) / 1000) : null;
        const fsStatus = fsAge !== null ? (fsAge < 120 ? `🟢 ONLINE (${fsAge}s ago)` : `🔴 OFFLINE (${fsAge}s ago)`) : "❓ Unknown";
        const macStatus = macAge !== null ? (macAge < 120 ? `🟢 ONLINE (${macAge}s ago)` : `🔴 OFFLINE (${macAge}s ago)`) : "❓ Unknown";
        const leaderRaw = await env.LEADFLOW_KV.get("leader:current");
        const leader = leaderRaw ? JSON.parse(leaderRaw) : {};
        const text = (
          `⚙️ *SYSTEM STATUS*\n━━━━━━━━━━━━━━━━━━\n` +
          `🔥 *Firestick:* ${fsStatus}\n` +
          `🖥️ *Mac:*       ${macStatus}\n` +
          `👑 *Active Leader:* \`${leader.device || "unknown"}\`\n` +
          `🌐 *Cloudflare Worker:* 🟢 ONLINE`
        );
        return tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
          text, parse_mode: "Markdown",
          reply_markup: { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] }
        });
      }

      let update;
      try { update = await request.json(); } catch { return new Response("OK"); }

      // Handle Messages
      if (update.message) {
        const msg = update.message;
        const chatId = msg.chat.id;
        const userId = msg.from.id;
        if (userId !== ALLOWED_USER) return new Response("OK");

        const text = msg.text || "";

        if (text === "/start" || text === "/menu") {
          await sendMenu(chatId);
        } else if (text.startsWith("/replied ")) {
          const query = text.replace("/replied ", "").trim();
          const leadsRaw = await env.LEADFLOW_KV.get("bot:leads_index");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const match = leads.find(l => l.name && l.name.toLowerCase().includes(query.toLowerCase()));
          
          if (!match) {
            await tgSend("sendMessage", { chat_id: chatId, text: `❌ Could not find any lead matching \`${query}\``, parse_mode: "Markdown" });
          } else {
            // Update stats
            const statsRaw = await env.LEADFLOW_KV.get("bot:stats");
            const stats = statsRaw ? JSON.parse(statsRaw) : {};
            stats.replied = (stats.replied || 0) + 1;
            await env.LEADFLOW_KV.put("bot:stats", JSON.stringify(stats));
            
            // Queue for scheduler to sync to SQLite
            const queueRaw = await env.LEADFLOW_KV.get("bot:replied_queue") || "[]";
            const queue = JSON.parse(queueRaw);
            queue.push({ business_id: parseInt(match.id), replied_at: new Date().toISOString() });
            await env.LEADFLOW_KV.put("bot:replied_queue", JSON.stringify(queue));
            
            await tgSend("sendMessage", { chat_id: chatId, text: `✅ *Success!* Marked \`${match.name}\` as Replied!`, parse_mode: "Markdown" });
          }
        } else if (text.startsWith("/search ")) {
          const query = text.replace("/search ", "").trim();
          const leadsRaw = await env.LEADFLOW_KV.get("bot:leads_index");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const matches = leads.filter(l => l.name && l.name.toLowerCase().includes(query.toLowerCase())).slice(0, 5);
          if (!matches.length) {
            await tgSend("sendMessage", { chat_id: chatId, text: `🔍 No results for \`${query}\``, parse_mode: "Markdown" });
          } else {
            let res = `🔍 *Results for '${query}':*\n\n`;
            for (const l of matches) {
              res += `• *${l.name}* (ID: ${l.id})\n  Category: ${l.category || "N/A"}\n  Status: \`${l.status}\`\n\n`;
            }
            await tgSend("sendMessage", { chat_id: chatId, text: res.slice(0, 4000), parse_mode: "Markdown" });
          }
        }
        return new Response("OK");
      }

      // Handle Callback Queries (button clicks)
      if (update.callback_query) {
        const cb = update.callback_query;
        const chatId = cb.message.chat.id;
        const msgId = cb.message.message_id;
        const userId = cb.from.id;
        const data = cb.data;

        await tgSend("answerCallbackQuery", { callback_query_id: cb.id });

        if (userId !== ALLOWED_USER) return new Response("OK");

        if (data === "menu") { await sendMenu(chatId, msgId); }
        else if (data === "stats") { await sendStats(chatId, msgId); }
        else if (data === "status") { await sendStatus(chatId, msgId); }
        else if (data === "drafts" || data.startsWith("drafts_")) {
          const offset = data.startsWith("drafts_") ? parseInt(data.split("_")[1]) : 0;
          await sendDrafts(chatId, msgId, offset);
        }
        else if (data.startsWith("ig_dm_")) {
          const offset = parseInt(data.split("_")[2]) || 0;
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id });
          await sendIgDm(chatId, msgId, offset);
        }
        else if (data.startsWith("ig_regen_")) {
          const parts = data.split("_");
          const bid = parseInt(parts[2]);
          const idx = parseInt(parts[3] || 0);
          
          const regenRaw = await env.LEADFLOW_KV.get("bot:ig_regen_queue") || "[]";
          const regenQ = JSON.parse(regenRaw);
          if (!regenQ.includes(bid)) {
            regenQ.push(bid);
            await env.LEADFLOW_KV.put("bot:ig_regen_queue", JSON.stringify(regenQ));
          }
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id, text: "🔄 Draft regeneration queued! The AI will rewrite it in a few seconds." });
        }
        else if (data.startsWith("ig_done_")) {
          const bid = data.split("_")[2];
          // Mark DM'd in KV queue
          const doneRaw = await env.LEADFLOW_KV.get("bot:ig_done_queue") || "[]";
          const doneQ = JSON.parse(doneRaw);
          doneQ.push({ business_id: parseInt(bid), done_at: new Date().toISOString() });
          await env.LEADFLOW_KV.put("bot:ig_done_queue", JSON.stringify(doneQ));
          // Remove from ig_leads
          const leadsRaw = await env.LEADFLOW_KV.get("bot:ig_leads");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const updated = leads.filter(l => String(l.business_id || l.id) !== String(bid));
          await env.LEADFLOW_KV.put("bot:ig_leads", JSON.stringify(updated));
          await tgSend("answerCallbackQuery", { callback_query_id: cb.id, text: "✅ Marked as DM'd!" });
          await sendIgDm(chatId, msgId, 0);
        }
        
        else if (data.startsWith("wa_dm_")) {
          const offset = parseInt(data.split("_")[2]) || 0;
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id });
          await sendWaDm(chatId, msgId, offset);
        }
        else if (data.startsWith("wa_regen_")) {
          const parts = data.split("_");
          const bid = parseInt(parts[2]);
          const idx = parseInt(parts[3] || 0);
          const regenRaw = await env.LEADFLOW_KV.get("bot:wa_regen_queue") || "[]";
          const regenQ = JSON.parse(regenRaw);
          if (!regenQ.includes(bid)) {
            regenQ.push(bid);
            await env.LEADFLOW_KV.put("bot:wa_regen_queue", JSON.stringify(regenQ));
          }
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id, text: "🔄 WA Draft regeneration queued!" });
        }
        else if (data.startsWith("wa_done_")) {
          const bid = data.split("_")[2];
          const doneRaw = await env.LEADFLOW_KV.get("bot:wa_done_queue") || "[]";
          const doneQ = JSON.parse(doneRaw);
          doneQ.push({ business_id: parseInt(bid), done_at: new Date().toISOString() });
          await env.LEADFLOW_KV.put("bot:wa_done_queue", JSON.stringify(doneQ));
          const leadsRaw = await env.LEADFLOW_KV.get("bot:wa_leads");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const updated = leads.filter(l => String(l.business_id || l.id) !== String(bid));
          await env.LEADFLOW_KV.put("bot:wa_leads", JSON.stringify(updated));
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id, text: "✅ Marked as WA Sent!" });
          await sendWaDm(chatId, msgId, 0);
        }
        else if (data.startsWith("wa_skip_")) {
          const bid = data.split("_")[2];
          const leadsRaw = await env.LEADFLOW_KV.get("bot:wa_leads");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const updated = leads.filter(l => String(l.business_id || l.id) !== String(bid));
          await env.LEADFLOW_KV.put("bot:wa_leads", JSON.stringify(updated));
          await tgSend("answerCallbackQuery", { callback_query_id: update.callback_query.id, text: "⏭️ Skipped" });
          await sendWaDm(chatId, msgId, 0);
        }

        else if (data.startsWith("ig_skip_")) {
          const bid = data.split("_")[2];
          const leadsRaw = await env.LEADFLOW_KV.get("bot:ig_leads");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const updated = leads.filter(l => String(l.business_id || l.id) !== String(bid));
          await env.LEADFLOW_KV.put("bot:ig_leads", JSON.stringify(updated));
          await tgSend("answerCallbackQuery", { callback_query_id: cb.id, text: "⏭️ Skipped" });
          await sendIgDm(chatId, msgId, 0);
        }
        else if (data.startsWith("ig_copy_")) {
          const idx = parseInt(data.split("_")[2]) || 0;
          const leadsRaw = await env.LEADFLOW_KV.get("bot:ig_leads");
          const leads = leadsRaw ? JSON.parse(leadsRaw) : [];
          const b = leads[idx % leads.length];
          if (b) {
            const demoUrl = b.demo_url || `https://leadflow-relay.chandango12.workers.dev/demo/${b.business_id || b.id}`;
            const dmMsg = buildDmMessage({ ...b, demo_url: demoUrl });
            await tgSend("answerCallbackQuery", { callback_query_id: cb.id });
            await tgSend("sendMessage", { chat_id: chatId, text: dmMsg }); // Plain text = easy long-press copy
          }
        }
        else if (data === "trigger") {
          await tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
            text: "🚀 *AUTOPILOT SCHEDULER*\n━━━━━━━━━━━━━━━━━━\nSelect action:",
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [
              [{ text: "📧 Trigger Send Batch", callback_data: "trig_send" }, { text: "🔍 Trigger Find Leads", callback_data: "trig_find" }],
              [{ text: "🔙 Main Menu", callback_data: "menu" }]
            ]}
          });
        }
        else if (data === "trig_send" || data === "trig_find") {
          const job = data === "trig_send" ? "send_leads" : "find_leads";
          await env.LEADFLOW_KV.put("bot:trigger_job", JSON.stringify({ job, triggered_at: new Date().toISOString() }));
          await tgSend("editMessageText", { chat_id: chatId, message_id: msgId,
            text: `✅ *Job Queued:* \`${job}\`\nFirestick will pick this up on next scheduler cycle.`,
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "🔙 Main Menu", callback_data: "menu" }]] }
          });
        }
        else if (data.startsWith("approve_")) {
          await handleApprove(chatId, msgId, data.split("_")[1]);
        }
        else if (data.startsWith("skip_")) {
          await handleSkip(chatId, msgId, data.split("_")[1]);
        }

        return new Response("OK");
      }

      return new Response("OK");
    }

    // ── Bot Webhook Registration Helper (/bot/register) ─────────────────────────
    if (url.pathname === "/bot/register" && method === "GET") {
      const headerToken = request.headers.get("X-Secret-Token") || url.searchParams.get("token");
      if (headerToken !== (env.SECRET_TOKEN || SECRET_TOKEN)) {
        return new Response("Unauthorized", { status: 401 });
      }
      const BOT_TOKEN = env.TELEGRAM_BOT_TOKEN;
      if (!BOT_TOKEN) return new Response("TELEGRAM_BOT_TOKEN not set", { status: 503 });
      const workerUrl = `${url.origin}/bot/webhook`;
      const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/setWebhook?url=${encodeURIComponent(workerUrl)}`);
      const result = await r.json();
      return new Response(JSON.stringify(result, null, 2), { headers: { "Content-Type": "application/json" } });
    }

    // Fallback: Status page
    return new Response(JSON.stringify({ status: "online", service: "leadflow-relay" }), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
