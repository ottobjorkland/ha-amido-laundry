/*
 * amido-laundry-card – book laundry rooms / saunas in an Amido "KundPortal" from a Home Assistant dashboard.
 * Unofficial, personal use only. See DISCLAIMER.md in the repository.
 *
 * Nothing is fetched in the background: data is requested only while this card is on screen and the browser
 * tab is visible (see `refresh_minutes`).
 */
const VERSION = "1.0.0";

const I18N = {
  sv: {
    updated: "Uppdaterad {t}", fetching: "Hämtar från portalen…", yours: "Dina bokningar", cancel: "Avboka", book: "Boka",
    mine: "Din tid", busy: "Upptagen", bookQ: "Boka passet?", cancelQ: "Avboka passet?", keep: "Behåll", back: "Avbryt",
    booked: "Bokat!", cancelled: "Avbokat:", failBook: "Det gick inte att boka", failCancel: "Det gick inte att avboka",
    noSlots: "Inga bokningsbara pass just nu.", today: "Idag", map: "Karta", directions: "Vägbeskrivning", fromYou: "från er",
    tvatt: "Tvättstuga", bastu: "Bastu", grov: "Grovtvätt", home: "Hemma", mapFail: "Kunde inte ladda kartan.",
    portal: "Öppna portalens egen bokningssida", loadFail: "Kunde inte hämta tider just nu.",
    e_blocked: "Pausar anrop en stund för att skydda portalen (till {until}).",
    e_auth: "Inloggningen misslyckades – kontrollera dina uppgifter.",
    e_auth_blocked: "Inloggning pausad efter fel – kontrollera uppgifterna och kör 'reset'.",
    e_network: "Kunde inte nå portalen just nu.", e_stale: "Portalens länk hade gått ut – försöker igen vid nästa uppdatering.",
    e_busy: "En annan förfrågan pågår – försök igen strax.", e_internal: "Ett internt fel inträffade.",
    e_invalid: "Ogiltig förfrågan.", e_service: "Kunde inte anropa Home Assistant (saknas shell_command-tjänsterna?).",
  },
  en: {
    updated: "Updated {t}", fetching: "Fetching from the portal…", yours: "Your bookings", cancel: "Cancel", book: "Book",
    mine: "Yours", busy: "Taken", bookQ: "Book this slot?", cancelQ: "Cancel this slot?", keep: "Keep", back: "Back",
    booked: "Booked!", cancelled: "Cancelled:", failBook: "Could not book", failCancel: "Could not cancel",
    noSlots: "No bookable slots right now.", today: "Today", map: "Map", directions: "Directions", fromYou: "from you",
    tvatt: "Laundry", bastu: "Sauna", grov: "Heavy laundry", home: "Home", mapFail: "Could not load the map.",
    portal: "Open the portal's own booking page", loadFail: "Could not fetch times right now.",
    e_blocked: "Pausing requests for a while to protect the portal (until {until}).",
    e_auth: "Login failed – check your credentials.",
    e_auth_blocked: "Login paused after an error – check your credentials and run 'reset'.",
    e_network: "Could not reach the portal right now.", e_stale: "The portal link had expired – will retry on the next refresh.",
    e_busy: "Another request is running – try again in a moment.", e_internal: "An internal error occurred.",
    e_invalid: "Invalid request.", e_service: "Could not call Home Assistant (are the shell_command services set up?).",
  },
};

const TYPES = [
  { id: "tvatt", icon: "mdi:washing-machine" },
  { id: "bastu", icon: "mdi:hot-tub" },
  { id: "grov", icon: "mdi:tumble-dryer" },
];
const typeOf = (o) => (/bastu|sauna/i.test(`${o.c} ${o.r}`) ? "bastu" : /grov|heavy|bulk/i.test(`${o.c} ${o.r}`) ? "grov" : "tvatt");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const LEAFLET_JS = { src: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", integrity: "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" };
const LEAFLET_CSS = { href: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", integrity: "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" };

const css = `
  :host { display: block; }
  ha-card { padding: 16px; position: relative; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; min-height: 40px; }
  .upd { font-size: 12px; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
  .spin { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--divider-color); border-top-color: var(--primary-color); animation: sp .8s linear infinite; }
  @keyframes sp { to { transform: rotate(360deg); } }
  .mapbtn { cursor: pointer; width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
            display: inline-flex; align-items: center; justify-content: center; padding: 0; }
  .mapbtn:hover { background: var(--secondary-background-color); }
  .mapbtn.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .mapbtn ha-icon { --mdc-icon-size: 22px; }
  .pop { line-height: 1.35; font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .pop b { font-size: 14px; }
  .pop a { display: inline-block; margin-top: 6px; padding: 6px 12px; border-radius: 999px; background: #03a9f4; color: #fff !important; text-decoration: none; font-weight: 600; font-size: 13px; }

  .mine { margin-bottom: 14px; display: flex; flex-direction: column; gap: 8px; }
  .minetitle { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .mrow { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px;
          background: color-mix(in srgb, var(--primary-color) 14%, transparent); border: 1px solid color-mix(in srgb, var(--primary-color) 40%, transparent); }
  .mrow ha-icon { color: var(--primary-color); }
  .mrow .txt { flex: 1; line-height: 1.25; color: var(--primary-text-color); }
  .mrow .txt b { font-weight: 600; }
  .mrow .txt small { display: block; color: var(--secondary-text-color); }

  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .chip { cursor: pointer; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
          padding: 7px 14px; border-radius: 999px; font: inherit; font-size: 14px; transition: all .15s; display: inline-flex; align-items: center; gap: 6px; }
  .chip:hover { background: var(--secondary-background-color); }
  .chip.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .chip ha-icon { --mdc-icon-size: 18px; }
  .chip small { opacity: .75; font-size: 12px; }
  .chips.types .chip { padding: 9px 18px; font-size: 15px; font-weight: 500; }
  .chips.rooms .chip { padding: 5px 12px; font-size: 13px; }

  #mapbox { display: none; margin: 0 0 12px; border-radius: 14px; overflow: hidden; border: 1px solid var(--divider-color); }
  #mapbox.show { display: block; }
  #map { height: 300px; width: 100%; background: var(--secondary-background-color); }
  .pin { display: flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; background: #5f6368; color: #fff;
         border: 2px solid #fff; box-shadow: 0 1px 6px rgba(0,0,0,.5); font-size: 12px; font-weight: 700; box-sizing: border-box; }
  .pin.sel { background: #03a9f4; width: 36px; height: 36px; }
  .pin.home { background: #e53935; font-size: 15px; }

  .day { display: flex; gap: 12px; padding: 10px 0; border-top: 1px solid var(--divider-color); align-items: center; }
  .dlabel { width: var(--dlabel-w, 78px); flex: none; line-height: 1.2; }
  .dlabel b { display: block; font-size: 15px; font-weight: 600; color: var(--primary-text-color); }
  .dlabel span { font-size: 12px; color: var(--secondary-text-color); }
  .tag { margin-left: 6px; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 6px; background: var(--primary-color); color: var(--text-primary-color, #fff); vertical-align: middle; text-transform: none; }
  .slots { display: grid; grid-template-columns: repeat(auto-fill, 84px); gap: 8px; flex: 1; justify-content: start; }
  .slot { box-sizing: border-box; width: 84px; height: 64px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; padding: 4px;
          border-radius: 12px; border: 1.5px solid transparent; font: inherit; color: var(--primary-text-color); background: transparent; }
  .slot.ghost { visibility: hidden; }
  .slot ha-icon { --mdc-icon-size: 18px; }
  .slot .t { font-size: 15px; font-weight: 600; letter-spacing: .01em; white-space: nowrap; }
  .slot .l { font-size: 11px; opacity: .85; white-space: nowrap; }
  .slot.free { cursor: pointer; border-color: var(--success-color, #43a047); background: color-mix(in srgb, var(--success-color, #43a047) 12%, transparent); }
  .slot.free ha-icon { color: var(--success-color, #43a047); }
  .slot.free:hover { background: color-mix(in srgb, var(--success-color, #43a047) 26%, transparent); }
  .slot.mine { cursor: pointer; background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .slot.mine:hover { filter: brightness(1.1); }
  .slot.busy { background: var(--secondary-background-color); border-color: transparent; color: var(--secondary-text-color); opacity: .6; }
  .slot.pending { pointer-events: none; opacity: .85; }
  .slot .mini { width: 16px; height: 16px; border-radius: 50%; border: 2px solid rgba(255,255,255,.35); border-top-color: #fff; animation: sp .8s linear infinite; margin: 1px 0; }
  .slot.free .mini { border-color: color-mix(in srgb, var(--success-color, #43a047) 35%, transparent); border-top-color: var(--success-color, #43a047); }
  @media (max-width: 600px) {
    ha-card { padding: 12px; }
    .day { flex-direction: column; align-items: stretch; gap: 6px; }
    .dlabel { width: auto; display: flex; align-items: baseline; gap: 8px; }
    .slots { grid-template-columns: repeat(auto-fill, 60px); gap: 6px; }
    .slot { width: 60px; height: 60px; padding: 2px; }
    .slot .t { font-size: 14px; }
    .slot .l { font-size: 10px; }
  }
  .empty, .err { padding: 16px; text-align: center; color: var(--secondary-text-color); }
  .banner { margin: 0 0 12px; padding: 10px 12px; border-radius: 10px; font-size: 14px; display: flex; gap: 8px; align-items: center; }
  .banner.ok { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); color: var(--primary-text-color); }
  .banner.bad { background: color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); color: var(--primary-text-color); }
  .banner.ok ha-icon { color: var(--success-color, #43a047); } .banner.bad ha-icon { color: var(--error-color, #db4437); }
  .skel { height: 64px; border-radius: 12px; margin: 10px 0; background: linear-gradient(90deg, var(--secondary-background-color) 25%, var(--divider-color) 37%, var(--secondary-background-color) 63%);
          background-size: 400% 100%; animation: sh 1.3s ease infinite; }
  @keyframes sh { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }

  .sheet { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 99; padding: 16px; }
  .panel { background: var(--card-background-color); border-radius: 18px; padding: 22px 22px 18px; max-width: 340px; width: 100%; box-shadow: 0 8px 30px rgba(0,0,0,.4); text-align: center; }
  .panel ha-icon { --mdc-icon-size: 40px; color: var(--primary-color); }
  .panel h2 { margin: 6px 0 4px; font-size: 20px; font-weight: 600; color: var(--primary-text-color); }
  .panel p { margin: 0 0 16px; color: var(--secondary-text-color); line-height: 1.4; }
  .panel p b { color: var(--primary-text-color); }
  .btns { display: flex; gap: 10px; }
  .btn { flex: 1; cursor: pointer; padding: 11px 12px; border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; border: 1px solid var(--divider-color);
         background: transparent; color: var(--primary-text-color); }
  .btn.go { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.del { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
  .foot { margin-top: 12px; text-align: center; }
  .foot a { color: var(--secondary-text-color); font-size: 12px; text-decoration: none; }
`;

class AmidoLaundryCard extends HTMLElement {
  setConfig(config) {
    this._config = Object.assign({
      title: "",
      language: "sv",
      default_object: "",          // object id, "Building · Room", or a part of that text
      refresh_minutes: 3,          // how often to refresh while the card is on screen (min 1)
      home: null,                  // { lat, lon, name }  – falls back to zone.home
      locations: {},               // { "Building name": { lat, lon } }  – enables distances + map
      map: true,
      portal_url: "",              // optional link to the landlord's own booking page
      services: { objects: "amido_objects", calendar: "amido_calendar", mine: "amido_mybookings", book: "amido_book", cancel: "amido_cancel" },
    }, config || {});
    this._config.refresh_minutes = Math.max(1, Number(this._config.refresh_minutes) || 3);
    this._t = I18N[this._config.language] || I18N.en;
    this.style.setProperty("--dlabel-w", this._config.language === "sv" ? "78px" : "96px");
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${css}</style>
        <ha-card><div id="top"></div><div id="mapbox"><div id="map"></div></div><div id="days"></div><div id="foot"></div><div id="sheet"></div></ha-card>`;
      this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    }
    Object.assign(this, { _objs: null, _sel: null, _cal: {}, _mine: null, _loading: {}, _confirm: null, _banner: null, _opt: {}, _pending: {}, _gone: {}, _showMap: false, _last: {}, _err: null });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._start();
    this._render();
  }

  connectedCallback() { if (this._hass && !this._timer) this._start(); }
  disconnectedCallback() { if (this._timer) { clearInterval(this._timer); this._timer = null; } }
  getCardSize() { return 10; }
  static getStubConfig() { return {}; }

  // ── data (only while the card is on screen) ───────────────────────────────
  _start() {
    if (this._timer) return;
    this._loadObjects();
    this._timer = setInterval(() => this._tick(), 20000);
  }
  _tick() {
    if (document.visibilityState !== "visible" || !this.isConnected || !this._sel) return;
    const age = (Date.now() - ((this._cal[this._sel] && this._cal[this._sel].ts) || 0)) / 60000;
    if (age >= this._config.refresh_minutes) { this._fetchCal(this._sel); this._fetchMine(); }
  }
  async _call(key, data) {
    try {
      const res = await this._hass.callWS({ type: "call_service", domain: "shell_command", service: this._config.services[key], service_data: data || {}, return_response: true });
      return JSON.parse((res.response && res.response.stdout) || "{}");
    } catch (e) { return { state: "Fel", code: "service" }; }
  }
  _errText(r) { return (this._t["e_" + r.code] || this._t.e_internal).replace("{until}", r.until || ""); }

  async _loadObjects() {
    const r = await this._call("objects");
    if (r.state !== "OK") { this._err = r; this._render(); return; }
    this._err = null; this._objs = r.objekt;
    const d = String(this._config.default_object || "").toLowerCase();
    const saved = (() => { try { return localStorage.getItem("amido_laundry_sel"); } catch (e) { return null; } })();
    const pick = (d && (this._objs.find((o) => o.id === d) || this._objs.find((o) => `${o.b} · ${o.r}`.toLowerCase() === d) || this._objs.find((o) => `${o.b} · ${o.r}`.toLowerCase().includes(d))))
      || (saved && this._objs.find((o) => o.id === saved)) || this._objs[0];
    if (pick) this._select(pick.id);
    this._fetchMine();
  }
  _select(id) {
    this._sel = id; this._banner = null;
    try { localStorage.setItem("amido_laundry_sel", id); } catch (e) { /* ignore */ }
    const c = this._cal[id];
    if (!c || Date.now() - c.ts > 60000) this._fetchCal(id);
    this._render();
  }
  async _fetchCal(id, fresh) {
    if (this._loading[id]) return;
    this._loading[id] = true; this._render();
    const r = await this._call("calendar", { id, fresh: fresh ? "--fresh" : "" });
    this._loading[id] = false;
    if (r.state === "OK") {
      this._cal[id] = { data: r, ts: Date.now(), err: null };
      for (const k of Object.keys(this._opt)) if (k.startsWith(`${id}|`) && !this._pending[k]) delete this._opt[k];  // fresh data replaces optimistic marks
    }
    else this._cal[id] = Object.assign(this._cal[id] || { data: null, ts: Date.now() - 30000 }, { err: r });
    this._render();
  }
  async _fetchMine() {
    const r = await this._call("mine");
    if (r.state === "OK") { this._mine = r.lista || []; this._gone = {}; }
    this._render();
  }

  // ── places ───────────────────────────────────────────────────────────────
  _home() {
    const c = this._config.home;
    if (c && c.lat != null) return { name: c.name || this._t.home, lat: c.lat, lon: c.lon };
    const z = this._hass.states["zone.home"];
    return z && z.attributes.latitude ? { name: this._t.home, lat: z.attributes.latitude, lon: z.attributes.longitude } : null;
  }
  _loc(b) { return (this._config.locations || {})[b] || null; }
  _dist(b) {
    const l = this._loc(b), h = this._home(); if (!l || !h) return null;
    const R = 6371000, rad = (x) => (x * Math.PI) / 180, dLat = rad(l.lat - h.lat), dLon = rad(l.lon - h.lon);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(h.lat)) * Math.cos(rad(l.lat)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  _fmt(m) { return m == null ? "" : m < 1000 ? `${this._config.language === "sv" ? "ca " : "~"}${Math.max(10, Math.round(m / 10) * 10)} m` : `${(m / 1000).toFixed(1).replace(".", this._config.language === "sv" ? "," : ".")} km`; }
  _dirUrl(b) {
    const l = this._loc(b), h = this._home();
    return `https://www.google.com/maps/dir/?api=1${h ? `&origin=${h.lat},${h.lon}` : ""}&destination=${l.lat},${l.lon}&travelmode=walking`;
  }
  _groups() {
    const m = {};
    for (const o of this._objs || []) (m[o.b] = m[o.b] || { b: o.b, rooms: [], dist: this._dist(o.b) }).rooms.push(Object.assign({ type: typeOf(o) }, o));
    return Object.values(m).sort((x, y) => (x.dist == null ? 1e9 : x.dist) - (y.dist == null ? 1e9 : y.dist) || x.b.localeCompare(y.b));
  }
  _cur() { return (this._objs || []).find((o) => o.id === this._sel) || null; }
  _isDefault(r) { const d = String(this._config.default_object || "").toLowerCase(); return !!d && (r.id === d || `${r.b} · ${r.r}`.toLowerCase().includes(d)); }
  _preferred(rooms) { return rooms.find((r) => this._isDefault(r)) || rooms[0]; }

  // ── events ───────────────────────────────────────────────────────────────
  _onClick(e) {
    const el = e.target.closest("[data-act]"); if (!el) return;
    const act = el.dataset.act, cur = this._cur(), gs = this._groups();
    if (act === "type") {
      const typed = gs.map((g) => g.rooms.filter((r) => r.type === el.dataset.type)).filter((rs) => rs.length);
      const pref = typed.find((rs) => rs.some((r) => this._isDefault(r))) || typed[0];
      if (pref) this._select(this._preferred(pref).id);
    } else if (act === "building") {
      const rs = (gs.find((x) => x.b === el.dataset.b) || { rooms: [] }).rooms;
      const same = rs.filter((r) => r.type === (cur && typeOf(cur)));
      const r = this._preferred(same.length ? same : rs); if (r) this._select(r.id);
    } else if (act === "room") this._select(el.dataset.id);
    else if (act === "map") { this._showMap = !this._showMap; if (!this._showMap) this._popupB = null; this._render(); }
    else if (act === "book" || act === "cancel") {
      this._confirm = { kind: act, id: el.dataset.id || this._sel, obj: el.dataset.obj, d: el.dataset.d, i: el.dataset.i, k: el.dataset.k, t: el.dataset.t };
      this._render();
    } else if (act === "close") { this._confirm = null; this._render(); }
    else if (act === "do") this._perform();
  }
  async _perform() {
    const c = this._confirm; this._confirm = null; this._banner = null;
    const book = c.kind === "book", key = `${c.id}|${c.d}|${c.k}`;
    this._opt[key] = book ? "mine" : "free"; this._pending[key] = true;
    if (!book) this._gone[key] = true;
    this._render();
    const r = await this._call(book ? "book" : "cancel", { id: c.id, date: c.d, slot: c.i !== undefined && c.i !== "" ? c.i : c.k });
    delete this._pending[key];
    const when = `${this._dayLabel(c.d)} · ${c.t}`;
    if (r.verified) this._banner = { ok: true, text: `${book ? this._t.booked : this._t.cancelled} ${when}` };
    else {
      delete this._opt[key]; delete this._gone[key];
      this._banner = { ok: false, text: `${book ? this._t.failBook : this._t.failCancel} ${when}${r.state === "Fel" && r.code ? ` – ${this._errText(r)}` : ""}` };
    }
    this._render();
    this._fetchCal(c.id, true); this._fetchMine();
    setTimeout(() => { if (this._banner && this._banner.ok) { this._banner = null; this._render(); } }, 8000);
  }

  // ── map (Leaflet is loaded lazily, with SRI, only when the map is opened) ──
  _leaflet() {
    if (window.L) return Promise.resolve();
    if (!window.__amidoLeaflet) {
      window.__amidoLeaflet = new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = LEAFLET_JS.src; s.integrity = LEAFLET_JS.integrity; s.crossOrigin = ""; s.onload = res; s.onerror = rej; document.head.appendChild(s);
      });
    }
    return window.__amidoLeaflet;
  }
  async _drawMap(sel) {
    const box = this.shadowRoot.getElementById("mapbox");
    box.classList.toggle("show", this._showMap);
    if (!this._showMap) return;
    try { await this._leaflet(); } catch (e) { this.shadowRoot.getElementById("map").innerHTML = `<div class="err">${esc(this._t.mapFail)}</div>`; return; }
    const L = window.L, h = this._home();
    if (!this._map) {
      if (!this.shadowRoot.getElementById("leafletcss")) {
        const l = document.createElement("link");
        l.id = "leafletcss"; l.rel = "stylesheet"; l.href = LEAFLET_CSS.href; l.integrity = LEAFLET_CSS.integrity; l.crossOrigin = "";
        this.shadowRoot.appendChild(l);
      }
      this._map = L.map(this.shadowRoot.getElementById("map"));
      // OpenStreetMap's tile policy requires a Referer; Home Assistant sends none by default → send the origin.
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, referrerPolicy: "origin", attribution: "© OpenStreetMap contributors" }).addTo(this._map);
      this._markers = L.layerGroup().addTo(this._map);
    }
    this._markers.clearLayers();
    const pts = [];
    if (h) {
      pts.push([h.lat, h.lon]);
      L.marker([h.lat, h.lon], { icon: L.divIcon({ className: "", html: '<div class="pin home">🏠</div>', iconSize: [30, 30], iconAnchor: [15, 15] }) })
        .bindTooltip(esc(h.name), { direction: "top", offset: [0, -14] }).addTo(this._markers);
    }
    for (const g of this._groups()) {
      const l = this._loc(g.b); if (!l) continue;
      pts.push([l.lat, l.lon]);
      const on = g.b === sel, nr = (g.b.match(/\d+/) || [g.b[0]])[0];
      const m = L.marker([l.lat, l.lon], { zIndexOffset: on ? 500 : 0, icon: L.divIcon({ className: "", html: `<div class="pin ${on ? "sel" : ""}">${esc(nr)}</div>`, iconSize: on ? [36, 36] : [30, 30], iconAnchor: on ? [18, 18] : [15, 15] }) });
      m.bindTooltip(`${esc(g.b)}${g.dist != null ? " · " + this._fmt(g.dist) : ""}`, { direction: "top", offset: [0, on ? -18 : -14] });
      m.bindPopup(`<div class="pop"><b>${esc(g.b)}</b>${g.dist != null ? `<br>${this._fmt(g.dist)} ${esc(this._t.fromYou)}` : ""}<br><a href="${esc(this._dirUrl(g.b))}" target="_blank" rel="noopener noreferrer">${esc(this._t.directions)}</a></div>`, { offset: [0, on ? -14 : -10], closeButton: false });
      m.on("click", () => { this._popupB = g.b; const cur = this._cur(); const rs = g.rooms.filter((r) => cur && r.type === typeOf(cur)); this._select(this._preferred(rs.length ? rs : g.rooms).id); });
      if (this._popupB === g.b) setTimeout(() => m.openPopup(), 0);
      m.addTo(this._markers);
    }
    this._map.invalidateSize();
    if (!this._fitted && pts.length) { this._map.fitBounds(pts, { padding: [30, 30], maxZoom: 18 }); this._fitted = true; }
  }

  // ── render ───────────────────────────────────────────────────────────────
  _dayLabel(iso) {
    const d = new Date(`${iso}T12:00:00`), loc = this._config.language === "sv" ? "sv-SE" : "en-GB";
    const wd = d.toLocaleDateString(loc, { weekday: "long" });
    return `${wd.charAt(0).toUpperCase()}${wd.slice(1)} ${d.toLocaleDateString(loc, { day: "numeric", month: "short" }).replace(/\./g, "")}`;
  }
  _render() {
    if (!this._hass || !this._config) return;
    const T = this._t, C = this._config;
    const cur = this._cur(), groups = this._groups();
    const c = cur && this._cal[cur.id], data = c && c.data;
    const busy = !!(cur && this._loading[cur.id]) || (!this._objs && !this._err);
    const locs = C.locations && Object.keys(C.locations).length && C.map !== false;

    let top = `<div class="head"><div class="upd">${busy ? `<div class="spin"></div>${esc(T.fetching)}` : data ? esc(T.updated.replace("{t}", (data.checked || "").slice(11, 16))) : ""}</div>
      ${locs ? `<button class="mapbtn ${this._showMap ? "on" : ""}" data-act="map" title="${esc(T.map)}"><ha-icon icon="mdi:map-marker-radius"></ha-icon></button>` : ""}</div>`;
    if (this._banner) top += `<div class="banner ${this._banner.ok ? "ok" : "bad"}"><ha-icon icon="${this._banner.ok ? "mdi:check-circle" : "mdi:alert-circle"}"></ha-icon>${esc(this._banner.text)}</div>`;
    if (this._err) top += `<div class="err">${esc(this._errText(this._err))}</div>`;

    const lista = (this._mine || []).filter((b) => !this._gone[`${b.id}|${b.date}|${b.k}`]);
    if (lista.length) {
      top += `<div class="mine"><div class="minetitle">${esc(T.yours)}</div>` + lista.map((b) => `
        <div class="mrow"><ha-icon icon="mdi:calendar-check"></ha-icon>
          <div class="txt"><b>${esc(this._dayLabel(b.date))}</b> · ${esc(b.t)}<small>${esc(b.b)} · ${esc(b.r)}</small></div>
          <button class="chip" data-act="cancel" data-id="${esc(b.id)}" data-d="${esc(b.date)}" data-k="${esc(b.k)}" data-t="${esc(b.t)}">${esc(T.cancel)}</button></div>`).join("") + `</div>`;
    }

    if (cur) {
      const curType = typeOf(cur);
      top += `<div class="chips types">` + TYPES.filter((t) => (this._objs || []).some((o) => typeOf(o) === t.id)).map((t) =>
        `<button class="chip ${t.id === curType ? "on" : ""}" data-act="type" data-type="${t.id}"><ha-icon icon="${t.icon}"></ha-icon>${esc(T[t.id])}</button>`).join("") + `</div>`;
      top += `<div class="chips">` + groups.filter((g) => g.rooms.some((r) => r.type === curType)).map((g) =>
        `<button class="chip ${g.b === cur.b ? "on" : ""}" data-act="building" data-b="${esc(g.b)}">${esc(g.b)}${g.dist != null ? `<small>${esc(this._fmt(g.dist))}</small>` : ""}</button>`).join("") + `</div>`;
      const rooms = (groups.find((g) => g.b === cur.b) || { rooms: [] }).rooms.filter((r) => r.type === curType);
      if (rooms.length > 1) top += `<div class="chips rooms">` + rooms.map((r) => `<button class="chip ${r.id === cur.id ? "on" : ""}" data-act="room" data-id="${esc(r.id)}">${esc(r.r)}</button>`).join("") + `</div>`;
    }
    this._zone("top", top);

    let days = "";
    if (cur) {
      if (!data && busy) days = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
      else if (!data) days = `<div class="err">${esc(c && c.err ? this._errText(c.err) : T.loadFail)}</div>`;
      else {
        const dagar = data.dagar || [], today = new Date().toLocaleDateString("sv-SE");
        const N = dagar.reduce((m, d) => Math.max(m, ...d.p.map((p) => p.i + 1)), 0);
        if (!dagar.length) days = `<div class="empty">${esc(T.noSlots)}</div>`;
        days += dagar.map((d) => {
          const byI = {}; d.p.forEach((p) => { byI[p.i] = p; });
          let cells = ""; for (let i = 0; i < N; i++) cells += byI[i] ? this._slot(cur.id, d, byI[i]) : `<div class="slot ghost"></div>`;
          const [wd, rest] = (() => { const s = this._dayLabel(d.d).split(" "); return [s[0], s.slice(1).join(" ")]; })();
          return `<div class="day"><div class="dlabel"><b>${esc(wd)}${d.d === today ? `<span class="tag">${esc(T.today)}</span>` : ""}</b><span>${esc(rest)}</span></div><div class="slots">${cells}</div></div>`;
        }).join("");
        if (busy) days = `<div style="opacity:.55;pointer-events:none">${days}</div>`;
      }
    }
    this._zone("days", days);
    this._zone("foot", C.portal_url ? `<div class="foot"><a href="${esc(C.portal_url)}" target="_blank" rel="noopener noreferrer">${esc(T.portal)}</a></div>` : "");

    let sheet = "";
    if (this._confirm) {
      const k = this._confirm, book = k.kind === "book", o = (this._objs || []).find((x) => x.id === k.id);
      sheet = `<div class="sheet"><div class="panel"><ha-icon icon="${book ? "mdi:calendar-plus" : "mdi:calendar-remove"}"></ha-icon>
        <h2>${esc(book ? T.bookQ : T.cancelQ)}</h2>
        <p><b>${esc(this._dayLabel(k.d))}</b><br>${esc(k.t)}<br>${esc(o ? `${o.b} · ${o.r}` : "")}</p>
        <div class="btns"><button class="btn" data-act="close">${esc(book ? T.back : T.keep)}</button><button class="btn ${book ? "go" : "del"}" data-act="do">${esc(book ? T.book : T.cancel)}</button></div></div></div>`;
    }
    this._zone("sheet", sheet);
    if (cur) this._drawMap(cur.b);
  }

  _slot(id, d, p) {
    const key = `${id}|${d.d}|${p.k}`, st = this._opt[key] || p.s, pend = this._pending[key];
    const a = `data-id="${esc(id)}" data-d="${esc(d.d)}" data-i="${esc(p.i)}" data-t="${esc(p.t)}" data-k="${esc(p.k)}"`;
    const T = this._t;
    if (st === "free") return `<button class="slot free${pend ? " pending" : ""}" data-act="book" ${a}>${pend ? '<div class="mini"></div>' : '<ha-icon icon="mdi:plus-circle-outline"></ha-icon>'}<span class="t">${esc(p.t)}</span><span class="l">${esc(T.book)}</span></button>`;
    if (st === "mine") return `<button class="slot mine${pend ? " pending" : ""}" data-act="cancel" ${a}>${pend ? '<div class="mini"></div>' : '<ha-icon icon="mdi:check-circle"></ha-icon>'}<span class="t">${esc(p.t)}</span><span class="l">${esc(T.mine)}</span></button>`;
    return `<div class="slot busy"><ha-icon icon="mdi:lock"></ha-icon><span class="t">${esc(p.t)}</span><span class="l">${esc(T.busy)}</span></div>`;
  }

  _zone(id, html) {
    if (this._last[id] === html) return;
    this._last[id] = html;
    this.shadowRoot.getElementById(id).innerHTML = html;
  }
}

customElements.define("amido-laundry-card", AmidoLaundryCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "amido-laundry-card", name: "Amido laundry booking", description: `Book laundry rooms and saunas (unofficial) v${VERSION}` });
