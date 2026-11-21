/* Stream365 – nyhedskort og nyhedens pop-up (Fangarr 1.24.0).
   Bruges to steder: i guiden (guide.stream365.vip, hentes via appen nyt) og i forhåndsvisningen i Fangarr › Guide › Nyheder.
   Tegnes i sin egen "skygge" (shadow DOM), så guidens stilarter ikke kan ændre udseendet – og omvendt.
   Tekster fra Fangarr escapes altid. Farver og illustrationer laves af Fangarr selv (ingen fri HTML fra nyhederne). */
(function () {
"use strict";
if (window.S365News && window.S365News.v) return;
var FT = "Outfit,'DM Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif";
var FB = "'DM Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif";
var RM = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

var CSS_CARD =
":host{all:initial;display:block}*{box-sizing:border-box}" +
".wrap{padding:16px 16px 0;font:15px/1.5 " + FB + ";-webkit-font-smoothing:antialiased}" +
".card{position:relative;border-radius:22px;overflow:hidden;background:var(--bg);color:var(--ink);border:var(--border);touch-action:pan-y}" +
".art{display:block}.art svg{display:block;width:100%;height:auto}" +
".body{padding:4px 20px 20px}.noart .body{padding-top:20px}.noart.closable .body{padding-right:56px}" +
".top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}" +
".pill{background:var(--pillBg);color:var(--pillInk);font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;line-height:1.4}" +
".when{font-size:13px;font-weight:600}" +
"h2{margin:12px 0 0;font:800 28px/1.08 " + FT + ";letter-spacing:-.01em;text-wrap:balance;color:inherit}" +
"p{margin:10px 0 0;font-size:15px;line-height:1.5;color:var(--sub)}" +
".cd{display:flex;gap:8px;margin-top:16px;max-width:420px}.cd div{flex:1;background:var(--chip);border-radius:12px;padding:9px 0;text-align:center}" +
".cd b{display:block;font:800 22px/1 " + FT + "}.cd span{display:block;font-size:12px;font-weight:600;margin-top:4px}" +
".go{margin-top:16px;display:flex;align-items:center;justify-content:center;gap:8px;min-height:50px;width:100%;padding:0 20px;border:0;border-radius:14px;" +
"background:var(--btnBg);color:var(--btnInk);font:700 16px/1.2 " + FB + ";cursor:pointer;text-align:center}" +
".go:hover{filter:brightness(1.12)}.go:focus-visible,.x:focus-visible,.arr:focus-visible,.dot:focus-visible{outline:3px solid var(--ink);outline-offset:2px}" +
".x{position:absolute;top:6px;right:6px;width:44px;height:44px;border:0;border-radius:50%;background:var(--chip);color:var(--ink);display:grid;place-items:center;cursor:pointer;z-index:2}" +
".nav{display:flex;align-items:center;justify-content:center;gap:4px;margin-top:12px}" +
".arr{width:44px;height:44px;border:0;border-radius:50%;background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer}.arr:hover{background:var(--chip)}" +
".dots{display:flex;align-items:center}.dot{width:22px;height:44px;border:0;background:none;padding:0;display:grid;place-items:center;cursor:pointer}" +
".dot i{display:block;width:6px;height:6px;border-radius:3px;background:var(--ink);opacity:.3}.dot.on i{width:20px;opacity:1}" +
".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}" +
".wrap.flush{padding-left:0;padding-right:0}.wrap.wide{padding-top:20px}.wide .card{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,40%);align-items:center}" +
".wide .card.noart{display:block}.wide .art{grid-column:2;grid-row:1;padding:18px 18px 18px 0}.wide .body{grid-column:1;grid-row:1;padding:28px 28px 24px}" +
".wide.closable .art{padding-top:40px}.wide h2{font-size:34px}.wide .go{width:auto;display:inline-flex}.wide .nav{justify-content:flex-start;margin-left:-12px}";

var CSS_POP =
":host{all:initial}*{box-sizing:border-box}" +
".ov{position:fixed;inset:0;background:rgba(4,5,6,.74);display:flex;align-items:flex-end;justify-content:center;font:15px/1.5 " + FB + ";-webkit-font-smoothing:antialiased;" +
"opacity:0;transition:opacity .2s}.ov.in{opacity:1}" +
".sheet{position:relative;background:#121416;color:#E8ECEA;width:100%;max-height:calc(100% - 40px);border-radius:26px 26px 0 0;display:flex;flex-direction:column;" +
"overflow:hidden;box-shadow:0 -12px 40px rgba(0,0,0,.5);transform:translateY(40px);transition:transform .25s ease-out}.ov.in .sheet{transform:none}" +
".head{position:relative;padding:10px 16px 0;flex:none;touch-action:none}.grab{width:40px;height:5px;border-radius:3px;background:#3A3F43;margin:0 auto 12px}" +
".ban{background:var(--bg);border-radius:18px;overflow:hidden}.ban svg{display:block;width:100%;height:auto;max-height:150px}" +
".x{position:absolute;top:24px;right:24px;width:44px;height:44px;border:0;border-radius:50%;background:rgba(0,0,0,.28);color:#fff;display:grid;place-items:center;cursor:pointer}" +
".noban .head{min-height:40px}.noban .x{top:8px;right:12px;background:#22262A}" +
".scroll{flex:1;min-height:0;overflow-y:auto;padding:18px 20px 12px;overscroll-behavior:contain}" +
".top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.pill{background:var(--accent);color:var(--accentInk);font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;line-height:1.4}" +
".when{font-size:13px;font-weight:600;color:#B4BABE}" +
"h2{margin:10px 0 0;font:800 26px/1.12 " + FT + ";color:#fff;text-wrap:balance}.noban h2{padding-right:44px}" +
".price{margin-top:14px;display:flex;align-items:center;gap:14px;border:1px solid #23302B;background:#0E1412;border-radius:14px;padding:12px 16px;flex-wrap:wrap}" +
".price b{font:800 28px/1 " + FT + ";color:var(--accent);white-space:nowrap}.price span{font-size:14px;color:#C9CFCD}" +
".intro{margin:12px 0 0;color:#C9CFCD}h3{margin:20px 0 0;font:700 18px/1.3 " + FT + ";color:#fff}" +
"ol{list-style:none;margin:10px 0 0;padding:0;display:flex;flex-direction:column;gap:14px}li{display:flex;gap:12px;align-items:flex-start}" +
".no{flex:none;width:30px;height:30px;border-radius:50%;background:var(--accent);color:var(--accentInk);font:800 15px/30px " + FT + ";text-align:center}" +
".st{font-weight:700;color:#fff}.tx{font-size:14px;line-height:1.5;color:#B4BABE;margin-top:2px}" +
".sart{margin-top:8px;background:var(--bg);border-radius:12px;overflow:hidden;max-width:300px}.sart svg{display:block;width:100%;height:auto}" +
".foot{flex:none;padding:12px 20px 18px;border-top:1px solid #1E2124;display:flex;flex-direction:column;gap:8px}" +
".ok{min-height:50px;border:0;border-radius:14px;background:var(--accent);color:var(--accentInk);font:700 16px/1.2 " + FB + ";cursor:pointer}" +
".ct{display:flex;gap:8px;flex-wrap:wrap}.ct a{flex:1 1 160px;min-height:46px;border:1px solid #2F3438;border-radius:14px;color:#fff;text-decoration:none;" +
"display:flex;align-items:center;justify-content:center;gap:8px;font-weight:700;font-size:15px;padding:0 12px;text-align:center}.ct a:hover{border-color:var(--accent)}" +
".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}" +
".more{min-height:44px;border:0;background:none;color:#58D9AE;font:600 14px/1.3 " + FB + ";cursor:pointer;padding:0 8px}" +
"button:focus-visible,a:focus-visible{outline:3px solid #58D9AE;outline-offset:2px}" +
"@media(min-width:700px){.ov{align-items:center;padding:24px}.sheet{max-width:560px;border-radius:24px;max-height:calc(100% - 48px)}.grab{visibility:hidden;height:0;margin-bottom:6px}" +
".x{top:18px}.noban .x{top:10px}}" +
"@media(prefers-reduced-motion:reduce){.ov,.sheet{transition:none}}";

function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
function br(t) { return esc(t).replace(/\n/g, "<br>"); }
function col(v) { v = String(v || ""); return /^[#\w(),.%\s-]{1,40}$/.test(v) ? v : ""; }
function vars(c) {
  c = c || {};
  return ["bg", "ink", "sub", "pillBg", "pillInk", "btnBg", "btnInk", "chip", "border", "accent", "accentInk"]
    .map(function (k) { return "--" + k + ":" + (col(c[k]) || "initial"); }).join(";");
}
function svgOk(s) { s = String(s || ""); return /^<svg[\s>]/.test(s) && !/<script|on\w+\s*=|javascript:/i.test(s) ? s : ""; }
var X = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
var ARROW = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
var PREV = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>';
var NEXT = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';
function pad(n) { return (n < 10 ? "0" : "") + n; }
function left(end) { var s = Math.max(0, Math.floor(end - Date.now() / 1000)); return {d: Math.floor(s / 86400), h: Math.floor(s % 86400 / 3600), m: Math.floor(s % 3600 / 60)}; }
function when(n) { return n.theme === "tilbud" && n.end_text ? "Gælder til " + n.end_text : ""; }
function cdLabel(l) { return "Slutter om " + l.d + (l.d === 1 ? " dag, " : " dage, ") + l.h + (l.h === 1 ? " time og " : " timer og ") + l.m + (l.m === 1 ? " minut" : " minutter"); }

// ---------------------------------------------------------------- kortet
function Card(host, items, o) {
  this.host = host; this.o = o || {}; this.items = items || []; this.i = 0; this.seen = {};
  this.root = host.shadowRoot || (host.attachShadow ? host.attachShadow({mode: "open"}) : host);
  this.root.innerHTML = "<style>" + CSS_CARD + '</style><div class="wrap" role="region" aria-label="Nyheder"></div>';
  this.box = this.root.querySelector(".wrap");
  var me = this;
  this.box.addEventListener("click", function (e) { var b = e.target.closest("[data-act]"); if (b) me.act(b.getAttribute("data-act"), b); });
  var sx = null, sy = null;
  this.box.addEventListener("touchstart", function (e) { if (e.touches.length === 1) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; } }, {passive: true});
  this.box.addEventListener("touchend", function (e) {
    if (sx === null || me.items.length < 2) return;
    var dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy; sx = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) me.act(dx < 0 ? "next" : "prev");
  }, {passive: true});
  if (window.ResizeObserver) new ResizeObserver(function () { me.wide(); }).observe(host);
  else window.addEventListener("resize", function () { me.wide(); });
  if (!this.o.preview && window.IntersectionObserver) {
    this.vis = false;
    new IntersectionObserver(function (es) { me.vis = es[0].isIntersecting; me.watch(); }, {threshold: 0.5}).observe(host);
  }
  this.timer = setInterval(function () { me.tick(); }, 15000);
  this.render();
}
Card.prototype.wide = function () {
  var r = this.host.getBoundingClientRect();
  this.box.classList.toggle("wide", r.width >= 640);
  // i guiden: har siden selv luft i siderne, bruges den – så flugter kortet med guidens tekst
  if (this.o.guide) this.box.classList.toggle("flush", r.left >= 12 && window.innerWidth - r.right >= 12);
};
Card.prototype.cur = function () { return this.items[this.i]; };
Card.prototype.render = function (focus) {
  var n = this.cur();
  if (!n) { this.box.innerHTML = ""; this.host.style.display = "none"; return; }
  this.host.style.display = "";
  var total = this.items.length, art = svgOk(n.art), l = n.countdown && n.end_ts ? left(n.end_ts) : null, w = when(n);
  var h = '<section class="card' + (art ? "" : " noart") + (n.closable ? " closable" : "") + '" style="' + esc(vars(n.colors)) + '" aria-label="' +
    esc(total > 1 ? "Nyhed " + (this.i + 1) + " af " + total : "Nyhed") + '">';
  if (n.closable) h += '<button type="button" class="x" data-act="close" aria-label="Luk nyheden">' + X + "</button>";
  if (art) h += '<div class="art" aria-hidden="true">' + art + "</div>";
  h += '<div class="body"><div class="top"><span class="pill">' + esc(n.tag) + "</span>" + (w ? '<span class="when">' + esc(w) + "</span>" : "") + "</div>";
  h += "<h2>" + br(n.title) + "</h2>" + (n.text ? "<p>" + br(n.text) + "</p>" : "");
  if (l) h += '<div class="cd" role="timer" aria-label="' + esc(cdLabel(l)) + '"><div><b>' + pad(l.d) + '</b><span>dage</span></div><div><b>' + pad(l.h) +
    '</b><span>timer</span></div><div><b>' + pad(l.m) + "</b><span>min.</span></div></div>";
  if (n.btn && n.action !== "none") h += '<button type="button" class="go" data-act="go">' + esc(n.btn) + " " + ARROW + "</button>";
  if (total > 1) {
    h += '<div class="nav"><button type="button" class="arr" data-act="prev" aria-label="Forrige nyhed">' + PREV + '</button><div class="dots">';
    for (var k = 0; k < total; k++) h += '<button type="button" class="dot' + (k === this.i ? " on" : "") + '" data-act="dot" data-i="' + k + '" aria-label="Nyhed ' + (k + 1) +
      '"' + (k === this.i ? ' aria-current="true"' : "") + "><i></i></button>";
    h += '</div><button type="button" class="arr" data-act="next" aria-label="Næste nyhed">' + NEXT + "</button></div>";
  }
  this.box.innerHTML = h + "</div></section>";
  this.wide();
  if (focus) { var f = this.box.querySelector(focus); if (f) f.focus(); }
  this.watch();
};
Card.prototype.watch = function () {
  var me = this, n = this.cur();
  clearTimeout(this.seenT);
  if (!n || this.o.preview || !this.vis || this.seen[n.id]) return;
  this.seenT = setTimeout(function () { if (me.vis && me.cur() === n && !me.seen[n.id]) { me.seen[n.id] = 1; me.track(n, "seen"); } }, 1000);
};
Card.prototype.track = function (n, a) { if (this.o.track && n && n.id) this.o.track(n.id, a); };
Card.prototype.tick = function () {
  var now = Date.now() / 1000, n = this.cur();
  if (!this.o.preview) {
    var keep = this.items.filter(function (x) { return !x.end_ts || x.end_ts > now; });
    if (keep.length !== this.items.length) { this.items = keep; this.i = Math.min(this.i, Math.max(0, keep.length - 1)); this.render(); return; }
  }
  var cd = this.box.querySelector(".cd");
  if (cd && n && n.end_ts) {
    var l = left(n.end_ts), b = cd.querySelectorAll("b");
    b[0].textContent = pad(l.d); b[1].textContent = pad(l.h); b[2].textContent = pad(l.m); cd.setAttribute("aria-label", cdLabel(l));
  }
};
Card.prototype.stop = function () { clearInterval(this.timer); clearTimeout(this.seenT); };
Card.prototype.update = function (items) { this.items = items || []; this.i = Math.min(this.i, Math.max(0, this.items.length - 1)); this.render(); };
Card.prototype.act = function (a, el) {
  var n = this.cur(), total = this.items.length, me = this;
  if (!n) return;
  if (a === "next" || a === "prev") { this.i = (this.i + (a === "next" ? 1 : -1) + total) % total; this.render(el ? (a === "next" ? '[data-act="next"]' : '[data-act="prev"]') : null); }
  else if (a === "dot") { this.i = Number(el.getAttribute("data-i")) || 0; this.render('[data-act="dot"][data-i="' + this.i + '"]'); }
  else if (a === "close") {
    if (this.o.preview) { if (this.o.note) this.o.note("Kunden kan lukke kortet med krydset. Det huskes på enheden."); return; }
    this.track(n, "close");
    if (this.o.onClose) this.o.onClose(n.id);
    this.items.splice(this.i, 1); this.i = Math.min(this.i, Math.max(0, this.items.length - 1)); this.render(this.items.length ? ".go" : null);
  } else if (a === "go") {
    this.track(n, n.action === "popup" ? "popup" : "click");
    if (n.action === "popup" && n.popup) openPopup(n, this.o.contact, {preview: this.o.preview, track: function (x) { me.track(n, x); },
                                                          goSection: this.o.goSection, note: this.o.note, from: el});
    else if (n.action === "section") {
      if (this.o.preview) { if (this.o.note) this.o.note("Knappen fører til afsnittet " + (n.section_title || n.section) + " i guiden."); }
      else if (this.o.goSection) this.o.goSection(n.section);
    }
  }
};

// ---------------------------------------------------------------- pop-up'en
function openPopup(n, contact, o) {
  o = o || {};
  var p = n.popup; if (!p) return null;
  var host = document.createElement("div");
  host.setAttribute("data-s365-popup", "");
  host.style.cssText = "position:fixed;inset:0;z-index:2147483000;display:block";
  document.body.appendChild(host);
  var root = host.attachShadow ? host.attachShadow({mode: "open"}) : host;
  var art = svgOk(p.art), w = when(n), links = contact && p.contact ? contact : null;
  var h = "<style>" + CSS_POP + '</style><div class="ov' + (art ? "" : " noban") + '"><section class="sheet" role="dialog" aria-modal="true" aria-labelledby="s365pt" style="' +
    esc(vars(n.colors)) + '"><div class="head"><div class="grab" aria-hidden="true"></div>' + (art ? '<div class="ban" aria-hidden="true">' + art + "</div>" : "") +
    '<button type="button" class="x" data-act="close" aria-label="Luk">' + X + '</button></div><div class="scroll"><div class="top"><span class="pill">' + esc(n.tag) + "</span>" +
    (w ? '<span class="when">' + esc(w) + "</span>" : "") + '</div><h2 id="s365pt">' + br(p.title || n.title) + "</h2>";
  if (p.price) h += '<div class="price"><b>' + esc(p.price) + "</b>" + (p.price_sub ? "<span>" + esc(p.price_sub) + "</span>" : "") + "</div>";
  if (p.intro) h += '<p class="intro">' + br(p.intro) + "</p>";
  if (p.steps && p.steps.length) {
    h += "<h3>Sådan gør du</h3><ol>";
    p.steps.forEach(function (s, i) {
      var sa = svgOk(s.art);
      h += '<li><span class="no" aria-hidden="true">' + (i + 1) + '</span><div><div class="st"><span class="sr">Trin ' + (i + 1) + ": </span>" + br(s.title) + "</div>" +
        (s.text ? '<div class="tx">' + br(s.text) + "</div>" : "") + (sa ? '<div class="sart" aria-hidden="true">' + sa + "</div>" : "") + "</div></li>";
    });
    h += "</ol>";
  }
  h += '</div><div class="foot"><button type="button" class="ok" data-act="close">' + esc(p.close || "Forstået") + "</button>";
  if (links) {
    var lab = links.label || "Skriv til os";
    h += '<div class="ct">' + (links.messenger ? '<a href="' + esc(links.messenger) + '" target="_blank" rel="noopener" data-act="contact">' + esc(lab) + " på Messenger</a>" : "") +
      (links.telegram ? '<a href="' + esc(links.telegram) + '" target="_blank" rel="noopener" data-act="contact">' + esc(lab) + " på Telegram</a>" : "") + "</div>";
  }
  if (p.read && p.read.id) h += '<button type="button" class="more" data-act="read">Læs også: ' + esc(p.read.title || p.read.id) + " →</button>";
  root.innerHTML = h + "</div></section></div>";
  var ov = root.querySelector(".ov"), sheet = root.querySelector(".sheet"), head = root.querySelector(".head");
  var prevFocus = o.from || document.activeElement, html = document.documentElement, prevOverflow = html.style.overflow, done = false, pushed = false;
  html.style.overflow = "hidden";
  function close(viaBack) {
    if (done) return; done = true;
    html.style.overflow = prevOverflow;
    document.removeEventListener("keydown", key, true);
    window.removeEventListener("popstate", pop);
    if (pushed && !viaBack && history.state && history.state.s365pop) history.back();
    ov.classList.remove("in");
    setTimeout(function () { host.remove(); }, RM ? 0 : 200);
    if (prevFocus && prevFocus.focus) try { prevFocus.focus(); } catch (e) {}
  }
  function pop() { close(true); }
  function key(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab") return;
    var f = [].slice.call(root.querySelectorAll("button,a[href]")), a = root.activeElement;
    if (!f.length) return;
    if (e.shiftKey && (a === f[0] || !a)) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && a === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  }
  document.addEventListener("keydown", key, true);
  if (!o.preview && history.pushState) { try { history.pushState({s365pop: 1}, ""); pushed = true; window.addEventListener("popstate", pop); } catch (e) {} }
  ov.addEventListener("click", function (e) {
    if (e.target === ov) { close(); return; }
    var b = e.target.closest("[data-act]"); if (!b) return;
    var a = b.getAttribute("data-act");
    if (a === "close") close();
    else if (a === "contact") { if (o.track) o.track("contact"); }
    else if (a === "read") {
      close();
      if (o.preview) { if (o.note) o.note("\"Læs også\" fører til afsnittet " + (p.read.title || p.read.id) + " i guiden."); }
      else if (o.goSection) setTimeout(function () { o.goSection(p.read.id); }, pushed ? 120 : 0);
    }
  });
  // træk ned for at lukke (telefon)
  var y0 = null, dy = 0;
  head.addEventListener("touchstart", function (e) { if (e.touches.length === 1) { y0 = e.touches[0].clientY; dy = 0; sheet.style.transition = "none"; } }, {passive: true});
  head.addEventListener("touchmove", function (e) { if (y0 === null) return; dy = Math.max(0, e.touches[0].clientY - y0); sheet.style.transform = "translateY(" + dy + "px)"; }, {passive: true});
  head.addEventListener("touchend", function () { if (y0 === null) return; y0 = null; sheet.style.transition = ""; sheet.style.transform = ""; if (dy > 90) close(); });
  requestAnimationFrame(function () { ov.classList.add("in"); var x = root.querySelector(".x"); if (x) x.focus(); });
  return {close: close};
}

// ---------------------------------------------------------------- i guiden
var KEY = "s365_nyheder_lukket";
function closedList() { try { var a = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
function rememberClosed(id) { try { var a = closedList().filter(function (x) { return x !== id; }); a.push(id); localStorage.setItem(KEY, JSON.stringify(a.slice(-60))); } catch (e) {} }
var q = [], qt = null;
function flush() {
  if (!q.length) return;
  var b = JSON.stringify({events: q.splice(0, 20)});
  try { if (navigator.sendBeacon && navigator.sendBeacon("/api/stat", new Blob([b], {type: "application/json"}))) return; } catch (e) {}
  try { fetch("/api/stat", {method: "POST", credentials: "same-origin", keepalive: true, headers: {"Content-Type": "application/json"}, body: b}).catch(function () {}); } catch (e) {}
}
function track(id, a) { q.push({e: "news", id: id, a: a}); clearTimeout(qt); qt = setTimeout(flush, 1500); }
function goSection(id) {
  var el = document.getElementById(id); if (!el) return;
  el.scrollIntoView({behavior: RM ? "auto" : "smooth", block: "start"});
  if (el.animate && !RM) setTimeout(function () {
    el.animate([{boxShadow: "0 0 0 3px rgba(88,217,174,.95)"}, {boxShadow: "0 0 0 3px rgba(88,217,174,0)"}], {duration: 2400, easing: "ease-out"});
  }, 450);
}
function spot() {
  // Kortet skal stå under toppen (Menu/søgning) og over guidens overskrift ("Få mere ud af Plex").
  var h = document.querySelector("h1"), s = document.querySelector("section[id]");
  if (h && s && !h.closest("#s365s")) { var a = h; while (a.parentElement && !a.parentElement.contains(s)) a = a.parentElement; if (a.parentElement) return [a.parentElement, a]; }
  if (s && s.parentElement) return [s.parentElement, s];
  var g = document.querySelector(".gbar"); if (g && g.parentElement) return [g.parentElement, g.nextSibling];
  var st = document.getElementById("s365s");
  return [document.body, st ? st.nextSibling : document.body.firstChild];
}
function guide() {
  fetch("/api/nyheder", {credentials: "same-origin", cache: "no-store"}).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
    if (!d || !d.news || !d.news.length) return;
    var closed = closedList(), items = d.news.filter(function (n) { return closed.indexOf(n.id) < 0; });
    if (!items.length) return;
    var host = document.createElement("div");
    host.id = "s365n"; host.style.cssText = "display:block;position:relative;z-index:1";
    var sp = spot(); sp[0].insertBefore(host, sp[1] || null);
    new Card(host, items, {guide: true, contact: d.contact, track: track, goSection: goSection, onClose: rememberClosed});
  }).catch(function () {});
  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function () { if (document.hidden) flush(); });
}

window.S365News = {
  v: 1,
  card: function (host, items, o) { return new Card(host, items, o); },
  popup: openPopup,
  guide: guide
};
})();
