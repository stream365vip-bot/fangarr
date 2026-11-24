// Indstillinger: Fangarrs egne indstillinger (felterne står på flere sider), Telegram, eksport/import, apps og widget.
function renderSettings() {
  const s = S.settings;
  SET_NUM.forEach(k => $("s_" + k).value = s[k]);
  $("s_dry_run").checked = !!s.dry_run;
  $("s_pass_existing").checked = !!s.pass_existing;
  $("s_seerr_check").checked = !!s.seerr_check;
  $("s_rescue_grab").checked = !!s.rescue_grab;
  $("s_tg_buttons").checked = !!s.tg_buttons; $("s_prem_notify").checked = !!s.prem_notify;
  fillRuleSelect("s_prem_rule", "series"); $("s_prem_rule").insertAdjacentHTML("afterbegin", '<option value="0">Første aktive serieregel</option>'); $("s_prem_rule").value = String(s.prem_rule || 0);
  $("seerrInfo").textContent = S.features.seerr ? "Seerr er forbundet." : "Seerr er ikke forbundet – tilføj SEERR_URL og SEERR_APIKEY i fangarr.env for at bruge det.";
  loadGrab();
  $("version").textContent = "Fangarr " + S.features.version;
  $("dryWarn").innerHTML = s.dry_run ? "" :
    '<div class="warn">Prøvetilstand er slået fra – titler bliver tilføjet til Sonarr/Radarr for alvor.</div>';
}
async function saveSettings() {
  const body = {dry_run: $("s_dry_run").checked, pass_existing: $("s_pass_existing").checked, seerr_check: $("s_seerr_check").checked, rescue_grab: $("s_rescue_grab").checked,
                tg_buttons: $("s_tg_buttons").checked, prem_notify: $("s_prem_notify").checked, prem_rule: +$("s_prem_rule").value || 0};
  SET_NUM.forEach(k => body[k] = $("s_" + k).value);
  if (S.settings.dry_run && !body.dry_run &&
      !confirm("Slå prøvetilstand fra? Herefter tilføjer Fangarr titler til Sonarr/Radarr for alvor.")) return;
  try { S.settings = await api("/api/settings", {method: "PUT", body: JSON.stringify(body)}); renderSettings(); renderStatus(); toast("Indstillingerne er gemt"); }
  catch (e) { toast(e.message, true); }
}

// ---------- eksport / import
async function loadBackups() {
  try { const b = await api("/api/backups");
        $("backupList").innerHTML = b.length ? "Gemt på serveren: " + b.slice(0, 5).map(x => esc(x.name)).join(", ") + (b.length > 5 ? ` (+${b.length - 5} flere)` : "") : "Ingen eksportfiler på serveren endnu."; }
  catch (e) {}
}

async function backupNow() { try { await api("/api/backups/now", {method: "POST"}); loadBackups(); toast("Eksporten er gemt på serveren"); } catch (e) { toast(e.message, true); } }
async function importFile(inp) {
  const f = inp.files[0]; inp.value = ""; if (!f) return;
  if (!confirm(`Importér “${f.name}”? Dine nuværende regler og indstillinger bliver erstattet.`)) return;
  try { const r = await api("/api/import", {method: "POST", body: await f.text()});
        toast(`Importeret: ${r.rules} regler, ${r.settings} indstillinger, ${r.waitlist} på ventelisten`); load(); }
  catch (e) { toast(e.message, true); }
}


async function loadAppsCfg() {
  let c; try { c = await api("/api/apps/config"); } catch (e) { return; }
  showAppsCfg(c);
}
function showAppsCfg(c) {
  $("appsLinks").value = c.links || ""; $("appsExtra").value = c.extra || ""; $("appsSlug").textContent = c.slug || "apps";
  $("appsState").innerHTML = !c.enabled ? '<span style="color:var(--warn)">Slået fra: UPTIME_URL mangler i fangarr.env.</span>'
    : "Forsiden: slået til. Widget-adressen: " + (c.widget ? "<b>slået til</b>." : '<span style="color:var(--warn)">slået fra (WIDGET_KEY mangler i fangarr.env eller er kortere end 32 tegn)</span>.');
}
async function saveAppsCfg() {
  try { showAppsCfg(await api("/api/apps/config", {method: "PUT", body: JSON.stringify({links: $("appsLinks").value, extra: $("appsExtra").value})})); toast("Gemt"); loadApps(1); }
  catch (e) { toast(e.message, true); }
}

// ---------- Telegram (2.0): viser, om Stream365 Drift er sat op
function renderTelegram() {
  const on = S && S.features && S.features.telegram;
  $("tgState").innerHTML = on ? '<span class="conn"><i></i>Telegram <span>sat op – beskederne går til Stream365 Drift</span></span>'
    : '<span class="conn bad"><i></i>Telegram <span>ikke sat op – TELEGRAM_TOKEN og TELEGRAM_CHAT_ID mangler i fangarr.env</span></span>';
}
