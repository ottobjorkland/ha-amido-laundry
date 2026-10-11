#!/usr/bin/env python3
"""amido_laundry - read and book laundry-room / sauna slots in an Amido "KundPortal" booking portal.

UNOFFICIAL. Not affiliated with, endorsed by or supported by any landlord or by Amido.
Intended for *personal* use with *your own* account only. See DISCLAIMER.md.

Design goals (be a polite, human-like client):
  * on demand only - nothing runs in the background; every call is triggered by a person using the card
  * the exact same requests a browser would make, nothing more (no bulk crawling, no other accounts)
  * strict client-side rate limiting, caching, exponential back-off and a login circuit-breaker

Commands (each prints ONE line of JSON, exit code 0 so Home Assistant always gets a readable answer):
  objects                                  list bookable objects (cached 24 h)
  calendar <id> [--fresh]                  free / busy / own slots for one object (cached 2 min)
  mybookings                               your own bookings
  book   <id> <YYYY-MM-DD> <interval|HH:MM-HH:MM>
  cancel <id> <YYYY-MM-DD> <interval|HH:MM-HH:MM>
  reset                                    clear back-off / login block / cache

<id> is the object id returned by `objects` (LocationId-TypeId-GroupId).

Files (all in AMIDO_CONFIG_DIR, default /config; credentials/state/cache are created chmod 600):
  amido_credentials.json   {"username": "...", "password": "..."}      (provider "rikshem")
  amido_laundry.json       optional settings, see DEFAULTS
Secrets (password, link tokens) are never printed or logged.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import unquote, urljoin

import requests

__version__ = "1.0.0"

CONFIG_DIR = os.environ.get("AMIDO_CONFIG_DIR", "/config")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "amido_laundry.json")
CREDS_FILE = os.path.join(CONFIG_DIR, "amido_credentials.json")
STATE_FILE = os.path.join(CONFIG_DIR, "amido_state.json")
CACHE_FILE = os.path.join(CONFIG_DIR, "amido_cache.json")

DEFAULTS = {
    "provider": "rikshem",          # "rikshem" = log in via the landlord's portal; "manual" = use `menu_url`
    "menu_url": "",                 # only for provider "manual": a BookingMenu.aspx link (tokens expire!)
    "min_interval": 1.0,            # seconds between any two HTTP requests (hard floor 0.5)
    "calendar_ttl": 120,            # seconds a calendar is served from cache
    "objects_ttl": 86400,           # seconds the object list is cached
    "link_trust": 1800,             # seconds a stored portal link is trusted without re-checking
    "weeks": 3,                     # weeks of calendar to read (1-4)
    "timeout": 20,
    "max_logins_per_day": 6,
    "auth_block_hours": 6,
    "backoff_base": 30,             # seconds; doubles per consecutive failure, capped at backoff_max
    "backoff_max": 3600,
}

USER_AGENT = f"ha-amido-laundry/{__version__} (personal use; unofficial; low request rate)"
DAYS = ["Mån", "Tis", "Ons", "Tors", "Fre", "Lör", "Sön"]

RIKSHEM = {
    "portal": "https://minasidor.rikshem.se/",
    "bookable": "https://minasidor.rikshem.se/res/themes/rikshemmarket/pages/BookableResources.aspx",
    "login_prefix": "ctl00$ctl01$DefaultSiteContentPlaceHolder1$Col1$LoginControl1$",
}

log = logging.getLogger("amido_laundry")


class PortalError(Exception):
    """Expected, user-facing problem. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


# ── small helpers ─────────────────────────────────────────────────────────────
def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_private(path, data):
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def settings() -> dict:
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read(SETTINGS_FILE, {}).items() if k in DEFAULTS})
    if os.environ.get("AMIDO_MENU_URL"):  # handy for tests / landlords without a supported login flow
        s["provider"], s["menu_url"] = "manual", os.environ["AMIDO_MENU_URL"]
    s["min_interval"] = max(0.5, float(s["min_interval"]))
    s["weeks"] = min(4, max(1, int(s["weeks"])))
    return s


def out(**kw):
    kw.setdefault("checked", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(json.dumps(kw, ensure_ascii=False, separators=(",", ":")))


def acquire_lock(timeout: float = 90.0):
    """Serialise all invocations: concurrent card requests must queue, never hit the portal in parallel."""
    fd = os.open(os.path.join(CONFIG_DIR, "amido.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.time() > deadline:
                raise PortalError("busy", "another request is still running")
            time.sleep(0.2)


def valid_id(v: str) -> str:
    if not re.fullmatch(r"\d{1,9}-\d{1,9}-\d{1,9}", v or ""):
        raise PortalError("invalid", "invalid object id")
    return v


def valid_date(v: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v or ""):
        raise PortalError("invalid", "invalid date")
    try:
        return date.fromisoformat(v)
    except ValueError as e:
        raise PortalError("invalid", "invalid date") from e


def valid_slot(v: str) -> str:
    if not re.fullmatch(r"\d{1,2}|\d{2}:\d{2}\s*[-–]\s*\d{2}:\d{2}", v or ""):
        raise PortalError("invalid", "invalid slot")
    return v.replace("–", "-").replace(" ", "")


# ── polite HTTP: throttle + back-off + cache ──────────────────────────────────
class Portal:
    def __init__(self):
        self.cfg = settings()
        self.st = _read(STATE_FILE, {})
        self.cache = _read(CACHE_FILE, {})
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "sv,en;q=0.8"})

    # state ---------------------------------------------------------------
    def save(self):
        _write_private(STATE_FILE, self.st)
        _write_private(CACHE_FILE, self.cache)

    def _blocked(self):
        now = time.time()
        if self.st.get("blocked_until", 0) > now:
            until = time.strftime("%H:%M", time.localtime(self.st["blocked_until"]))
            raise PortalError("blocked", f"paused after errors until {until} (protects the portal)", until=until)

    def _fail(self):
        n = self.st.get("fail_count", 0) + 1
        self.st["fail_count"] = n
        wait = min(self.cfg["backoff_max"], self.cfg["backoff_base"] * 2 ** (n - 1))
        self.st["blocked_until"] = time.time() + wait
        self.save()

    def request(self, method: str, url: str, **kw):
        """Single HTTP request: honours back-off, spaces requests >= min_interval, never retries."""
        self._blocked()
        gap = self.cfg["min_interval"] - (time.time() - self.st.get("last_req", 0))
        if gap > 0:
            time.sleep(gap)
        self.st["last_req"] = time.time()
        kw.setdefault("timeout", self.cfg["timeout"])
        try:
            r = self.session.request(method, url, **kw)
        except requests.RequestException as e:
            log.warning("network error: %s", type(e).__name__)
            self._fail()
            raise PortalError("network", "could not reach the portal") from e
        if r.status_code == 429 or r.status_code >= 500:
            log.warning("portal answered HTTP %s", r.status_code)
            self._fail()
            raise PortalError("network", f"portal answered HTTP {r.status_code}")
        if self.st.get("fail_count"):
            self.st["fail_count"] = 0
            self.st["blocked_until"] = 0
        return r

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    # authentication → portal link ---------------------------------------
    def _login_rikshem(self) -> str:
        now = time.time()
        if self.st.get("auth_blocked_until", 0) > now:
            raise PortalError("auth_blocked", "login paused after a failed login - check your credentials, then run `reset`")
        recent = [t for t in self.st.get("logins", []) if t > now - 86400]
        if len(recent) >= self.cfg["max_logins_per_day"]:
            raise PortalError("auth_blocked", "daily login limit reached (protects your account)")
        creds = _read(CREDS_FILE, {})
        user, pwd = creds.get("username"), creds.get("password")
        if not (user and pwd):
            raise PortalError("auth", f"no credentials: create {os.path.basename(CREDS_FILE)}")
        if os.stat(CREDS_FILE).st_mode & 0o077:
            log.warning("%s is readable by other users - run chmod 600", os.path.basename(CREDS_FILE))
        self.st["logins"] = recent + [now]
        self.save()
        cfg = RIKSHEM
        page = self.get(cfg["portal"])
        form = hidden_fields(page.text)
        p = cfg["login_prefix"]
        form.update({p + "txtUserID": user, p + "txtPassword": pwd, p + "btnLogin": "Logga in", p + "hdnSelectedTab": "password"})
        r = self.post(cfg["portal"], data=form, allow_redirects=True)
        if "logga ut" not in r.text.lower():
            self._auth_failed()
        portal = self.get(cfg["bookable"])
        m = re.search(r'href="([^"]*Laundry\.aspx\?[^"]*)"', unescape(portal.text), re.I)
        if not m:
            self._auth_failed("no laundry booking link found on the portal page")
        r = self.get(urljoin(cfg["bookable"], m.group(1)), allow_redirects=True)
        if "BookingMenu" not in r.url:
            self._auth_failed("portal did not forward to the booking system")
        return r.url

    def _auth_failed(self, msg="login failed - check your credentials"):
        self.st["auth_blocked_until"] = time.time() + self.cfg["auth_block_hours"] * 3600
        self.save()
        raise PortalError("auth", msg)

    def menu_url(self, force=False) -> str:
        if self.cfg["provider"] == "manual":
            if not self.cfg["menu_url"]:
                raise PortalError("auth", "provider 'manual' needs menu_url in amido_laundry.json")
            return self.cfg["menu_url"]
        url = self.st.get("menu_url")
        if url and not force and time.time() - self.st.get("menu_ts", 0) < self.cfg["link_trust"]:
            return url
        if url and not force:  # old link: verify with one request before logging in again
            r = self.get(url)
            if r.status_code == 200 and "Välj bokningsobjekt" in r.text:
                self.st["menu_ts"] = time.time()
                self.save()
                return url
        url = self._login_rikshem()
        self.st.update(menu_url=url, menu_ts=time.time())
        self.cache.pop("objects", None)
        self.save()
        return url

    # objects -------------------------------------------------------------
    def objects(self, force=False) -> list:
        c = self.cache.get("objects")
        if c and not force and time.time() - c["ts"] < self.cfg["objects_ttl"]:
            return c["list"]
        url = self.menu_url()
        r = self.get(url)
        objs = parse_menu(r.text)
        if not objs:
            raise PortalError("stale", "booking menu was empty (link expired?)")
        self.cache["objects"] = {"ts": time.time(), "list": objs}
        self.save()
        return objs

    def find(self, oid: str) -> dict:
        for o in self.objects():
            if o["id"] == oid:
                return o
        raise PortalError("invalid", "unknown object id")

    def base(self) -> str:
        return self.menu_url().split("BookingMenu.aspx")[0]


# ── parsing (pure functions, unit-tested) ─────────────────────────────────────
def hidden_fields(html: str) -> dict:
    out_ = {}
    for tag in re.findall(r"<input[^>]*>", html):
        if 'type="hidden"' in tag:
            n = re.search(r'name="([^"]*)"', tag)
            v = re.search(r'value="([^"]*)"', tag)
            if n:
                out_[n.group(1)] = unescape(v.group(1)) if v else ""
    return out_


def fix_apt(rel: str) -> str:
    """Menu links carry the apartment parameter double-encoded (%252c); browsers send it single-encoded."""
    return re.sub(r"%25([0-9a-fA-F]{2})", r"%\1", rel)


def pretty_parts(desc: str):
    parts = [p for p in desc.split("/") if p]
    building, room = parts[0], parts[-1]
    cat = parts[1] if len(parts) > 2 else ""
    if cat and building.lower().endswith(cat.lower()):
        building = building[: -len(cat)].strip()
    return building, cat, room


def parse_menu(html: str) -> list:
    t = unescape(html)
    objs = []
    for n in re.findall(r"__doPostBack\('TreeView1','(s[^']*)'\)", t):
        rel = fix_apt(n.replace("\\\\", "\\").split("\\")[-1])
        g = lambda k: (re.search(rf"[?&]{k}=([^&]*)", rel) or [None, ""])[1]
        if not (g("LocationId") and g("TypeId") and g("GroupId")):
            continue
        desc = unquote(g("Description"))
        building, cat, room = pretty_parts(desc)
        objs.append({"id": f"{g('LocationId')}-{g('TypeId')}-{g('GroupId')}", "b": building, "c": cat, "r": room,
                     "rel": rel})
    return objs


CALL_RE = re.compile(r"(Book|Cancel|BookDialog)\(\"([^\"]*)\",\s*\"([^\"]*)\",\s*\"([^\"]*)\",\s*\"([^\"]*)\",\s*(\d+),\s*(?:true|false),\s*\"([^\"]*)\"\)")
TIME_RE = re.compile(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})")


def short_t(t: str) -> str:
    m = TIME_RE.search(t or "")
    if not m:
        return t or ""
    f = lambda x: x[:2] if x.endswith(":00") else x
    return f"{f(m.group(1))}–{f(m.group(2))}"


def parse_week(t: str) -> dict:
    mon = re.search(r'id="TextboxMondayOfWeek"[^>]*value="([^"]+)"|value="([\d-]+)"[^>]*id="TextboxMondayOfWeek"', t)
    monday = datetime.strptime(mon.group(1) or mon.group(2), "%Y-%m-%d").date() if mon else None
    a = t.index('<table id="Table1"')
    table = t[a:t.index("</table>", a)]
    rows = re.split(r"<tr[^>]*>", table)[2:]  # [0]=before, [1]=day headers
    slots = []
    for i, row in enumerate(rows):
        for d, c in enumerate(re.findall(r"<td[^>]*>.*?</td>", row, re.S)):
            u = unescape(c)
            tm = TIME_RE.search(u) or TIME_RE.search(unescape(re.sub(r"<[^>]+>", " ", c)))
            call = CALL_RE.search(u)
            low = c.lower()
            if "ej bokningsbart" in low:
                s = "na"
            elif call and call.group(1) == "Cancel":
                s = "mine"
            elif call and call.group(1) in ("Book", "BookDialog"):
                s = "mine" if "bokat av dig" in low or "du har bokat" in low else "free"
            elif "upptaget" in low or "fullbokat" in low:
                s = "busy"
            else:
                s = "na"
            day = monday + timedelta(days=d) if monday else None
            slots.append({"date": call.group(5) if call else (day.isoformat() if day else ""), "i": i, "d": d,
                          "t": f"{tm.group(1)}-{tm.group(2)}" if tm else "", "s": s})
    return {"monday": monday, "slots": slots}


def build_days(weeks: list, today: date, horizon: int = 14) -> list:
    days = {}
    for w in weeks:
        for sl in w["slots"]:
            if not sl["date"] or sl["s"] == "na":
                continue
            d = date.fromisoformat(sl["date"])
            if today <= d < today + timedelta(days=horizon):
                days.setdefault(d, []).append({"i": sl["i"], "t": short_t(sl["t"]), "k": sl["t"], "s": sl["s"]})
    return [{"d": d.isoformat(), "wd": DAYS[d.weekday()], "n": d.day, "m": d.month,
             "p": sorted(ps, key=lambda x: x["i"])} for d, ps in sorted(days.items())]


def parse_bookings(html: str, objects: list, today: date) -> list:
    res = []
    for r_ in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        line = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(r_))).strip()
        m = re.search(r"([A-Za-zåäöÅÄÖ]+)\s+(\d{1,2})/(\d{1,2})\s+(\d{2}:\d{2})-(\d{2}:\d{2})\s+(.*?)(?:\s+Avboka)?$", line)
        if not m:
            continue
        day, mon = int(m.group(2)), int(m.group(3))
        year = today.year + (1 if mon < today.month - 6 else 0)
        building, _cat, room = pretty_parts(m.group(6).strip())
        oid = next((o["id"] for o in objects if o["b"] == building and o["r"] == room), "")
        f = lambda x: x[:2] if x.endswith(":00") else x
        res.append({"id": oid, "date": f"{year:04d}-{mon:02d}-{day:02d}", "wd": m.group(1), "n": day, "m": mon,
                    "t": f"{f(m.group(4))}–{f(m.group(5))}", "k": f"{m.group(4)}-{m.group(5)}", "b": building, "r": room})
    return res


# ── commands ──────────────────────────────────────────────────────────────────
def fetch_calendar(p: Portal, obj: dict) -> list:
    base = p.base()
    r = p.get(base + obj["rel"])
    if r.status_code != 200 or '<table id="Table1"' not in r.text:
        raise PortalError("stale", "could not read the calendar (link expired?)")
    t, weeks = r.text, []
    for w in range(p.cfg["weeks"]):
        weeks.append(parse_week(t))
        if w == p.cfg["weeks"] - 1:
            break
        f = {k: unescape(v) for k, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', t)
             if k.startswith("__") or k in ("DbId", "TextboxMondayOfWeek")}
        action = unescape(re.search(r'<form[^>]*action="([^"]+)"', t).group(1))
        f["ButtonNextWeek.x"], f["ButtonNextWeek.y"] = "5", "5"
        t = p.post(base + action.lstrip("./"), data=f).text
        if '<table id="Table1"' not in t:
            break
    return weeks


def with_stale_retry(p: Portal, fn):
    """Run fn; if the stored portal link turned out to be stale, log in ONCE more (limited by the login breaker)."""
    try:
        return fn()
    except PortalError as e:
        if e.code != "stale" or p.cfg["provider"] == "manual":
            raise
        p.cache.pop("objects", None)
        p.menu_url(force=True)
        return fn()


def cmd_objects(p: Portal):
    objs = with_stale_retry(p, p.objects)
    out(state="OK", objekt=[{k: o[k] for k in ("id", "b", "c", "r")} for o in objs])


def cmd_calendar(p: Portal, oid: str, fresh: bool):
    oid = valid_id(oid)
    c = p.cache.get(f"cal:{oid}")
    if c and not fresh and time.time() - c["ts"] < p.cfg["calendar_ttl"]:
        data = dict(c["data"])
        data["cached"] = True
        out(**data)
        return

    def run():
        obj = p.find(oid)
        weeks = fetch_calendar(p, obj)
        days = build_days(weeks, date.today())
        return {"state": "OK", "id": oid, "objekt": f"{obj['b']} · {obj['r']}", "dagar": days,
                "antal_fria": sum(1 for d in days for s in d["p"] if s["s"] == "free")}

    data = with_stale_retry(p, run)
    data["checked"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p.cache[f"cal:{oid}"] = {"ts": time.time(), "data": data}
    p.save()
    out(**data)


def cmd_mybookings(p: Portal):
    def run():
        objs = p.objects()
        r = p.get(p.menu_url().replace("BookingMenu.aspx", "Bookings.aspx"))
        return parse_bookings(r.text, objs, date.today()), r.text

    lista, html = with_stale_retry(p, run)
    if not lista and "inga bokningar" not in html.lower():
        out(state="OK", antal=0, lista=[], note="no bookings recognised")
        return
    out(state="OK", antal=len(lista), lista=lista)


def cmd_change(p: Portal, action: str, oid: str, day: str, slot: str):
    oid, d, slot = valid_id(oid), valid_date(day), valid_slot(slot)

    def run():
        obj = p.find(oid)
        interval = slot
        if not slot.isdigit():  # time range given -> look up the interval index in the (cached) calendar
            weeks = fetch_calendar(p, obj)
            hit = next((s for w in weeks for s in w["slots"] if s["date"] == d.isoformat() and s["t"] == slot), None)
            if not hit:
                raise PortalError("invalid", "no such slot")
            interval = str(hit["i"])
        m = re.search(r"[?&]DatabaseId=(\d+)", obj["rel"])
        apt = re.search(r"[?&]Apartment=([^&]*)", obj["rel"])
        if not (m and apt):
            raise PortalError("stale", "object link incomplete")
        group = obj["id"]
        # Body is sent exactly like the portal's own script: the apartment value is already URL-encoded.
        body = (f"adminBooking=False&DatabaseId={m.group(1)}&Apartment={apt.group(1)}&GroupId={group}"
                f"&Date={d.isoformat()}&BookingInterval={int(interval)}")
        r = p.post(p.base() + ("Booking.asmx/BookPass" if action == "book" else "Booking.asmx/CancelPass"),
                   data=body.encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"})
        code = re.search(r"<Code>([^<]*)</Code>", r.text)
        msg = re.search(r"<Message>([^<]*)</Message>", r.text)
        mine = re.search(r"<ThisCustomer>(\d+)</ThisCustomer>", r.text)
        code = code.group(1) if code else "?"
        n = int(mine.group(1)) if mine else -1
        ok = code == "B000" and ((n > 0) if action == "book" else (n == 0))
        return ok, code, unescape(msg.group(1)) if msg else f"HTTP {r.status_code}", obj

    ok, code, msg, obj = with_stale_retry(p, run)
    p.cache.pop(f"cal:{oid}", None)  # next calendar read must be fresh
    p.save()
    out(state="OK" if ok else "Fel", action=action, objekt=f"{obj['b']} · {obj['r']}", date=d.isoformat(), code=code,
        message=msg, verified=ok)


def cmd_reset(p: Portal):
    for k in ("blocked_until", "fail_count", "auth_blocked_until", "logins"):
        p.st.pop(k, None)
    p.cache.clear()
    p.save()
    out(state="OK", message="back-off, login block and cache cleared")


def main(argv) -> int:
    logging.basicConfig(level=os.environ.get("AMIDO_LOG", "WARNING"), stream=sys.stderr,
                        format="%(levelname)s amido_laundry: %(message)s")
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1].lower(), [a for a in argv[2:] if not a.startswith("--")]
    try:
        lock = acquire_lock()  # noqa: F841  (held until the process exits)
        p = Portal()
        try:
            if cmd == "objects":
                cmd_objects(p)
            elif cmd == "calendar" and args:
                cmd_calendar(p, args[0], "--fresh" in argv)
            elif cmd == "mybookings":
                cmd_mybookings(p)
            elif cmd in ("book", "cancel") and len(args) == 3:
                cmd_change(p, cmd, *args)
            elif cmd == "reset":
                cmd_reset(p)
            else:
                out(state="Fel", code="usage", fel="unknown command or arguments")
                return 2
        finally:
            p.save()
    except PortalError as e:
        out(state="Fel", code=e.code, fel=e.message, **e.extra)
    except Exception as e:  # never leak details (URLs/tokens) - only the exception type
        log.error("unexpected error: %s", type(e).__name__)
        out(state="Fel", code="internal", fel=type(e).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
