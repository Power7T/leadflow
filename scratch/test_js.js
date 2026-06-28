const lead = {
  "id": 2642,
  "name": "Jaybees Valet Laundry",
  "category": "Cleaning",
  "pitch_type": "leadflow_saas",
  "interactions": [],
  "demo_tunnel_url": null,
  "maps_url": "https://facebook.com/..."
};

let ctaButtons = '';
if (lead.pitch_type === 'both' || lead.pitch_type === 'website_new') {
  ctaButtons += `
    <div style="background:rgba(255,255,255,0.02); border:1px solid var(--border); padding:16px; border-radius:8px; margin-bottom:20px;">
      <h4 style="margin:0 0 10px 0;">🌐 Web Design Demo Site</h4>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px 0;">Build a modern local landing page with built-in reviews, WhatsApp, and AI Chatbot.</p>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" onclick="buildDemo(${lead.id}, '')" id="btn-build-${lead.id}">⚡ Build & Deploy Demo</button>
        <a href="/demo/${lead.id}" id="demo-link-${lead.id}" target="_blank" class="btn btn-ghost" style="display:${lead.demo_tunnel_url ? 'inline-flex' : 'none'};">👁️ View Demo</a>
      </div>
    </div>
  `;
}
if (lead.pitch_type === 'both' || lead.pitch_type === 'leadflow_saas') {
  ctaButtons += `
    <div style="background:rgba(0, 200, 150, 0.05); border:1px solid rgba(0, 200, 150, 0.15); padding:16px; border-radius:8px; margin-bottom:20px;">
      <h4 style="margin:0 0 10px 0; color:#00c896;">⚡ LeadFlow SaaS CRM Campaign</h4>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px 0;">Offer them LeadFlow access so they can scrape, manage, and automate outreach to Airbnb hosts directly.</p>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" onclick="buildDemo(${lead.id}, 'saas-')" id="btn-build-saas-${lead.id}" style="background:#00c896; border-color:#00c896;">⚡ Build SaaS Demo</button>
        <a href="/demo/${lead.id}" id="demo-link-saas-${lead.id}" target="_blank" class="btn btn-ghost" style="display:${lead.demo_tunnel_url ? 'inline-flex' : 'none'}; border-color:#00c896; color:#00c896;">👁️ View Dashboard</a>
      </div>
    </div>
  `;
}

let interactionsHtml = '';
if (lead.interactions && lead.interactions.length > 0) {
  interactionsHtml = `<div style="margin-top:20px;"><h4 style="margin-bottom:10px;">Outreach Log</h4><div style="display:flex; flex-direction:column; gap:8px;">`;
  lead.interactions.forEach(i => {
    const isAI = i.is_inbound === 0;
    interactionsHtml += `
      <div style="padding:10px; border-radius:6px; background:${isAI ? 'rgba(37,99,235,0.1)' : 'rgba(255,255,255,0.04)'}; border:1px solid ${isAI ? 'rgba(37,99,235,0.2)' : 'var(--border)'};">
        <div style="font-size:10px; color:var(--text-dim); margin-bottom:4px;">${isAI ? 'Outbound Pitch' : 'Prospect Reply'} · ${i.timestamp}</div>
        <div style="font-size:12.5px; white-space:pre-wrap;">${i.content}</div>
      </div>
    `;
  });
  interactionsHtml += `</div></div>`;
}

let finalHtml = `
  <div class="card" style="padding:30px;">
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:15px;">
      <div>
        <h2 style="margin:0;">${lead.name}</h2>
        <p style="margin:4px 0 0; color:var(--text-dim); font-size:13px;">Category: ${lead.category || 'N/A'} · Source: Facebook Miami Group</p>
      </div>
      ${lead.maps_url ? `<a href="${lead.maps_url}" target="_blank" class="btn btn-ghost" style="font-size:11px; padding:6px 12px;">👥 Open Facebook Post</a>` : ''}
    </div>

    ${ctaButtons}

    <!-- Outreach Generator -->
    <div style="background:rgba(255,255,255,0.01); border:1px solid var(--border); padding:20px; border-radius:8px;">
      <h4 style="margin:0 0 12px 0;">✉ Dynamic Outreach Composer</h4>
      <div style="display:flex; gap:8px; margin-bottom:12px;">
        <button class="btn btn-ghost" onclick="generateOutreach(${lead.id}, 'email')">Generate Cold Email</button>
        <button class="btn btn-ghost" onclick="generateOutreach(${lead.id}, 'instagram')">Generate DM Copy</button>
      </div>
      
      <div id="outreachComposer-${lead.id}" style="display:none; margin-top:15px; text-align:left;">
        <div style="font-size:11px; text-transform:uppercase; color:var(--text-dim); font-weight:600; margin-bottom:6px;">Draft Subject/Message:</div>
        <textarea id="draftText-${lead.id}" style="width:100%; height:150px; padding:10px; background:var(--bg); border:1px solid var(--border); border-radius:6px; color:#fff; outline:none; font-family:inherit; font-size:13px; line-height:1.45;"></textarea>
        <div style="display:flex; gap:10px; margin-top:12px; justify-content:flex-end;">
          <button class="btn btn-primary" onclick="sendOutreach(${lead.id})" id="btn-send-${lead.id}">📨 Send via Email</button>
        </div>
      </div>
    </div>

    ${interactionsHtml}
  </div>
`;

console.log("SUCCESS");
