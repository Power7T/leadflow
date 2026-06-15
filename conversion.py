"""
Conversion layer for demo sites.

Turns demo *viewers* into booked clients. Injected into every generated demo,
it adds three things on top of the static site:

  1. A sticky "book a call" CTA bar that slides up after the visitor scrolls in.
  2. An exit-intent / timed modal that fires once, asking them to book the build.
  3. Engagement beacons (scroll depth + CTA clicks) sent back to LeadFlow so the
     operator gets a real-time ntfy ping the moment a prospect shows buying intent.

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
<!-- LEADFLOW CONVERSION LAYER -->
<style>
  .lf-cta-bar{position:fixed;left:0;right:0;bottom:0;z-index:9998;
    display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;
    padding:14px 20px;background:rgba(10,10,12,.92);backdrop-filter:blur(12px);
    border-top:1px solid rgba(255,255,255,.12);
    transform:translateY(120%);transition:transform .45s cubic-bezier(.2,.8,.2,1);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#fff}
  .lf-cta-bar.show{transform:translateY(0)}
  .lf-cta-bar p{margin:0;font-size:15px;font-weight:500}
  .lf-cta-bar p b{color:#4d9fff}
  .lf-btn{display:inline-flex;align-items:center;gap:8px;border:none;cursor:pointer;
    text-decoration:none;font-size:15px;font-weight:700;padding:12px 22px;border-radius:999px;
    transition:transform .15s,box-shadow .15s}
  .lf-btn:hover{transform:translateY(-2px)}
  .lf-btn-primary{background:linear-gradient(135deg,#4d9fff,#2563eb);color:#fff;
    box-shadow:0 6px 20px rgba(77,159,255,.45)}
  .lf-btn-ghost{background:rgba(255,255,255,.08);color:#fff;border:1px solid rgba(255,255,255,.18)}
  .lf-modal-bg{position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;
    background:rgba(0,0,0,.72);backdrop-filter:blur(6px);padding:20px;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
  .lf-modal-bg.show{display:flex;animation:lf-fade .3s ease}
  @keyframes lf-fade{from{opacity:0}to{opacity:1}}
  .lf-modal{position:relative;max-width:460px;width:100%;background:#101014;color:#fff;
    border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:38px 32px;text-align:center;
    box-shadow:0 30px 80px rgba(0,0,0,.6);animation:lf-pop .35s cubic-bezier(.2,.9,.3,1.2)}
  @keyframes lf-pop{from{transform:scale(.9);opacity:0}to{transform:scale(1);opacity:1}}
  .lf-modal h2{margin:0 0 12px;font-size:26px;line-height:1.25}
  .lf-modal h2 b{color:#4d9fff}
  .lf-modal p{margin:0 0 26px;font-size:16px;line-height:1.6;color:#b9b9c3}
  .lf-modal .lf-btn{width:100%;justify-content:center;font-size:17px;padding:16px}
  .lf-modal .lf-sub{margin-top:16px;font-size:13px;color:#7a7a88}
  .lf-x{position:absolute;top:14px;right:16px;background:none;border:none;color:#777;
    font-size:26px;line-height:1;cursor:pointer}
  .lf-x:hover{color:#fff}
  @media(max-width:600px){.lf-cta-bar p{flex-basis:100%;text-align:center}}
</style>

<div class="lf-cta-bar" id="lfBar">
  <p>👀 Like this design for <b>__NAME__</b>?</p>
  <a href="__BOOKING__" target="_blank" rel="noopener" class="lf-btn lf-btn-primary"
     data-lf="cta_book_bar">Book a free call →</a>
  __WA_BTN__
</div>

<div class="lf-modal-bg" id="lfModal">
  <div class="lf-modal">
    <button class="lf-x" id="lfX" aria-label="Close">&times;</button>
    <h2>Want this site live for <b>__NAME__</b>?</h2>
    <p>This demo was built specifically for you. Book a free 15-minute call and
       I'll have it live on your domain — no obligation, no upfront cost.</p>
    <a href="__BOOKING__" target="_blank" rel="noopener" class="lf-btn lf-btn-primary"
       data-lf="cta_book_modal">Claim this website →</a>
    <div class="lf-sub">Built by __AGENCY__</div>
  </div>
</div>

<script>
(function(){
  var BEACON="__BEACON__", BID="__BID__", sent={};
  function ping(ev){
    if(sent[ev]||!BEACON)return; sent[ev]=true;
    try{ fetch(BEACON+"/api/engage?bid="+BID+"&ev="+ev,{mode:"no-cors",keepalive:true}); }catch(e){}
  }
  // sticky CTA bar appears once they've scrolled in a bit
  var bar=document.getElementById("lfBar"), barShown=false;
  function onScroll(){
    var sc=window.scrollY, h=document.body.scrollHeight-window.innerHeight;
    var pct=h>0?sc/h:0;
    if(pct>0.12&&!barShown){bar.classList.add("show");barShown=true;ping("scroll_in");}
    if(pct>0.9)ping("scroll_90");
  }
  window.addEventListener("scroll",onScroll,{passive:true});

  // modal: exit-intent on desktop, timed on mobile, once per visit
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
  // high-intent: CTA clicks -> instant operator alert
  document.querySelectorAll("[data-lf]").forEach(function(el){
    el.addEventListener("click",function(){ping(el.getAttribute("data-lf"));});
  });
})();
</script>
"""


def cta_block(business: dict) -> str:
    """Return the full conversion-layer HTML to inject before </body>."""
    name = (business.get("name") or "your business")
    booking_url = os.getenv("BOOKING_URL", "https://www.fiverr.com/sellers/chandangosavi/")
    agency_name = os.getenv("AGENCY_NAME", "Chandan Gosavi")

    wa = _wa_link(business)
    wa_btn = (
        f'<a href="{wa}" target="_blank" rel="noopener" class="lf-btn lf-btn-ghost" '
        f'data-lf="cta_whatsapp">WhatsApp</a>'
        if wa else ""
    )
    return (
        _TEMPLATE
        .replace("__NAME__", name)
        .replace("__BOOKING__", booking_url)
        .replace("__AGENCY__", agency_name)
        .replace("__WA_BTN__", wa_btn)
        .replace("__BEACON__", public_base())
        .replace("__BID__", str(business.get("id", "")))
    )
