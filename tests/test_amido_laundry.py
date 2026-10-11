"""Offline tests: parsing, validation and the "polite client" guarantees. No network access is used."""
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import amido_laundry as al  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "CONFIG_DIR", str(tmp_path))
    for name, const in (("amido_laundry.json", "SETTINGS_FILE"), ("amido_credentials.json", "CREDS_FILE"),
                        ("amido_state.json", "STATE_FILE"), ("amido_cache.json", "CACHE_FILE")):
        monkeypatch.setattr(al, const, str(tmp_path / name))
    return tmp_path


# ── parsing ─────────────────────────────────────────────────────────────────
def test_fix_apt_single_encodes_apartment():
    assert al.fix_apt("Apartment=1%252c2%253a3") == "Apartment=1%2c2%3a3"


def test_parse_menu_ids_and_names():
    objs = al.parse_menu((FIX / "menu.html").read_text(encoding="utf-8"))
    assert [o["id"] for o in objs] == ["11-12-13", "11-12-14", "21-22-23"]
    assert objs[0]["b"] == "Example Street 1"           # trailing category word is stripped from the building
    assert objs[0]["r"] == "Laundry room 1"
    assert objs[2]["c"] == "SAUNA"
    assert "%252c" not in objs[0]["rel"] and "%2c" in objs[0]["rel"]


def test_parse_week_states_and_dates():
    wk = al.parse_week((FIX / "week.html").read_text(encoding="utf-8"))
    assert wk["monday"] == date(2000, 1, 3)
    by = {(s["i"], s["d"]): s for s in wk["slots"]}
    assert by[(0, 0)]["s"] == "na"                         # not bookable
    assert by[(0, 1)]["s"] == "free" and by[(0, 1)]["date"] == "2000-01-04"
    assert by[(1, 2)]["s"] == "mine"
    assert by[(2, 3)]["s"] == "busy"
    assert by[(0, 1)]["t"] == "07:00-10:00"


def test_build_days_hides_unbookable_and_past_days():
    wk = al.parse_week((FIX / "week.html").read_text(encoding="utf-8"))
    days = al.build_days([wk], date(2000, 1, 4))
    assert days[0]["d"] == "2000-01-04" and days[0]["wd"] == "Tis"
    assert all(s["s"] != "na" for d in days for s in d["p"])
    assert al.build_days([wk], date(2000, 1, 4), horizon=1) == days[:1]


def test_parse_bookings_maps_to_object_id():
    objs = al.parse_menu((FIX / "menu.html").read_text(encoding="utf-8"))
    res = al.parse_bookings((FIX / "bookings.html").read_text(encoding="utf-8"), objs, date(2000, 1, 1))
    assert res == [{"id": "11-12-13", "date": "2000-01-03", "wd": "Monday", "n": 3, "m": 1, "t": "07–10",
                    "k": "07:00-10:00", "b": "Example Street 1", "r": "Laundry room 1"}]


# ── validation: nothing user-controlled reaches the shell/URL unchecked ──────────
@pytest.mark.parametrize("bad", ["", "x; rm -rf /", "1-2", "1-2-3-4", "a-b-c", "1-2-3 ", "$(id)"])
def test_object_id_rejects_garbage(bad):
    with pytest.raises(al.PortalError):
        al.valid_id(bad)


def test_valid_inputs():
    assert al.valid_id("11-12-13") == "11-12-13"
    assert al.valid_date("2026-10-20") == date(2026, 10, 20)
    assert al.valid_slot("3") == "3" and al.valid_slot("07:00–10:00") == "07:00-10:00"
    for bad in ("2026-13-40", "tomorrow", "2026-1-1"):
        with pytest.raises(al.PortalError):
            al.valid_date(bad)
    with pytest.raises(al.PortalError):
        al.valid_slot("soon")


# ── polite client guarantees ──────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status=200, text="ok", url="https://x/"):
        self.status_code, self.text, self.url = status, text, url


def test_requests_are_spaced_by_min_interval(cfgdir, monkeypatch):
    p = al.Portal()
    p.cfg["min_interval"] = 0.6
    sleeps = []
    monkeypatch.setattr(al.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(p.session, "request", lambda *a, **k: FakeResp())
    p.get("https://x/")
    p.get("https://x/")
    assert sleeps and 0 < sleeps[-1] <= 0.6                # second request had to wait


def test_backoff_doubles_and_blocks_further_requests(cfgdir, monkeypatch):
    p = al.Portal()
    calls = []
    monkeypatch.setattr(p.session, "request", lambda *a, **k: calls.append(1) or FakeResp(503))
    monkeypatch.setattr(al.time, "sleep", lambda s: None)
    with pytest.raises(al.PortalError) as e1:
        p.get("https://x/")
    assert e1.value.code == "network" and p.st["fail_count"] == 1
    first_block = p.st["blocked_until"] - time.time()
    assert first_block == pytest.approx(p.cfg["backoff_base"], abs=2)
    n = len(calls)
    with pytest.raises(al.PortalError) as e2:               # blocked: must NOT touch the network
        p.get("https://x/")
    assert e2.value.code == "blocked" and len(calls) == n
    p.st["blocked_until"] = 0                               # window over → next failure doubles the wait
    with pytest.raises(al.PortalError):
        p.get("https://x/")
    assert p.st["blocked_until"] - time.time() == pytest.approx(2 * p.cfg["backoff_base"], abs=2)


def test_backoff_is_capped(cfgdir, monkeypatch):
    p = al.Portal()
    p.st["fail_count"] = 50
    p._fail()
    assert p.st["blocked_until"] - time.time() <= p.cfg["backoff_max"] + 1


def test_success_clears_backoff(cfgdir, monkeypatch):
    p = al.Portal()
    p.st.update(fail_count=3, blocked_until=0)
    monkeypatch.setattr(p.session, "request", lambda *a, **k: FakeResp())
    monkeypatch.setattr(al.time, "sleep", lambda s: None)
    p.get("https://x/")
    assert p.st["fail_count"] == 0


def test_failed_login_trips_breaker_and_never_retries(cfgdir, monkeypatch):
    (cfgdir / "amido_credentials.json").write_text(json.dumps({"username": "u", "password": "p"}))
    os.chmod(cfgdir / "amido_credentials.json", 0o600)
    p = al.Portal()
    monkeypatch.setattr(al.time, "sleep", lambda s: None)
    posts = []

    def fake_request(method, url, **kw):
        if method == "POST":
            posts.append(url)
        return FakeResp(text="<html>login form, no logout link</html>")

    monkeypatch.setattr(p.session, "request", fake_request)
    with pytest.raises(al.PortalError) as e:
        p.menu_url()
    assert e.value.code == "auth" and len(posts) == 1
    with pytest.raises(al.PortalError) as e2:               # breaker open: no second login attempt
        p.menu_url()
    assert e2.value.code == "auth_blocked" and len(posts) == 1


def test_daily_login_limit(cfgdir):
    (cfgdir / "amido_credentials.json").write_text(json.dumps({"username": "u", "password": "p"}))
    os.chmod(cfgdir / "amido_credentials.json", 0o600)
    p = al.Portal()
    p.st["logins"] = [time.time() - 60] * p.cfg["max_logins_per_day"]
    with pytest.raises(al.PortalError) as e:
        p.menu_url()
    assert e.value.code == "auth_blocked"


def test_calendar_is_served_from_cache_without_requests(cfgdir, monkeypatch, capsys):
    p = al.Portal()
    data = {"state": "OK", "id": "1-2-3", "objekt": "A · B", "dagar": [], "antal_fria": 0, "checked": "x"}
    p.cache["cal:1-2-3"] = {"ts": time.time(), "data": data}
    monkeypatch.setattr(p.session, "request", lambda *a, **k: pytest.fail("network used despite fresh cache"))
    al.cmd_calendar(p, "1-2-3", fresh=False)
    out = json.loads(capsys.readouterr().out)
    assert out["cached"] is True and out["state"] == "OK"


def test_state_files_are_private(cfgdir):
    p = al.Portal()
    p.st["x"] = 1
    p.save()
    for name in ("amido_state.json", "amido_cache.json"):
        assert (os.stat(cfgdir / name).st_mode & 0o077) == 0


def test_user_agent_is_honest():
    assert "Mozilla" not in al.USER_AGENT and "unofficial" in al.USER_AGENT


def test_errors_never_contain_secrets(cfgdir, monkeypatch, capsys):
    (cfgdir / "amido_credentials.json").write_text(json.dumps({"username": "SECRETUSER", "password": "SECRETPASS"}))
    os.chmod(cfgdir / "amido_credentials.json", 0o600)
    monkeypatch.setattr(al.requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(al.requests.ConnectionError("boom SECRETPASS")))
    monkeypatch.setattr(al.time, "sleep", lambda s: None)
    al.main(["amido_laundry.py", "objects"])
    shown = capsys.readouterr()
    assert "SECRET" not in shown.out and "SECRET" not in shown.err
