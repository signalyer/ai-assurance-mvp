"""Usage analytics: login events, page views, active session tracking, geolocation.

Storage: append-only JSONL at data/usage_events.jsonl + data/usage_sessions.jsonl.
Timezone: all timestamps stored UTC; display helpers format as America/Chicago (CST/CDT).
Geolocation: ip-api.com free tier (HTTP, no key, 45 req/min). Cached in-memory per IP for 24h.
"""

from __future__ import annotations

import ipaddress
import json
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CST = ZoneInfo("America/Chicago")  # CST/CDT — DST-aware

DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(exist_ok=True)
EVENTS_FILE = DATA_DIR / "usage_events.jsonl"
SESSIONS_FILE = DATA_DIR / "usage_sessions.jsonl"

INACTIVITY_TIMEOUT_S = 10 * 60  # 10 minutes

_lock = threading.Lock()
_geo_cache: dict[str, dict[str, Any]] = {}
_geo_cache_ts: dict[str, float] = {}
GEO_CACHE_TTL_S = 24 * 60 * 60

# In-memory mirror of active sessions for fast reads. Rebuilt from disk at startup.
_sessions: dict[str, dict[str, Any]] = {}


# ---------- helpers ---------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = _utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def format_cst(iso_utc: str) -> str:
    """ISO-UTC string -> 'YYYY-MM-DD HH:MM:SS CST'."""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(CST)
        tz_abbr = local.strftime("%Z") or "CST"
        return local.strftime("%Y-%m-%d %H:%M:%S") + " " + tz_abbr
    except Exception:
        return iso_utc


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast


def client_ip_from_headers(headers: dict[str, str]) -> str:
    """Extract real client IP. App Service sets X-Forwarded-For; first hop is the user."""
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    if xff:
        first = xff.split(",")[0].strip()
        # App Service appends ":port" sometimes — strip
        if ":" in first and first.count(":") == 1:
            first = first.split(":")[0]
        return first
    return headers.get("x-azure-clientip") or headers.get("X-Azure-ClientIP") or ""


def geolocate(ip: str) -> dict[str, Any]:
    """Return {country, region, city, lat, lon, isp, timezone}. Empty dict on failure/private IP."""
    if not ip or _is_private_ip(ip):
        return {}
    now = time.time()
    if ip in _geo_cache and (now - _geo_cache_ts.get(ip, 0)) < GEO_CACHE_TTL_S:
        return _geo_cache[ip]
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,timezone,lat,lon,isp,query"
        req = urllib.request.Request(url, headers={"User-Agent": "aigovern-analytics/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if data.get("status") == "success":
            geo = {
                "country": data.get("country", ""),
                "region": data.get("regionName", ""),
                "city": data.get("city", ""),
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "isp": data.get("isp", ""),
                "timezone": data.get("timezone", ""),
            }
            _geo_cache[ip] = geo
            _geo_cache_ts[ip] = now
            return geo
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    _geo_cache[ip] = {}
    _geo_cache_ts[ip] = now
    return {}


# ---------- event log -------------------------------------------------------

def _append_jsonl(path: Path, record: dict) -> None:
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def log_event(event_type: str, *, user: str, session_id: str, ip: str,
              user_agent: str, path: str = "", extra: dict | None = None) -> None:
    """Append a usage event. event_type: LOGIN | LOGOUT | PAGE_VIEW | API_CALL | SESSION_EXPIRED."""
    geo = geolocate(ip)
    rec = {
        "ts_utc": _utc_iso(),
        "event": event_type,
        "user": user,
        "session_id": session_id,
        "ip": ip or "",
        "country": geo.get("country", ""),
        "region": geo.get("region", ""),
        "city": geo.get("city", ""),
        "isp": geo.get("isp", ""),
        "user_agent": (user_agent or "")[:300],
        "path": path,
    }
    if extra:
        rec.update(extra)
    _append_jsonl(EVENTS_FILE, rec)


# ---------- session store ---------------------------------------------------

def _load_sessions_from_disk() -> None:
    """Rebuild _sessions from the append-only sessions log. Idempotent."""
    global _sessions
    if not SESSIONS_FILE.exists():
        return
    out: dict[str, dict] = {}
    with SESSIONS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = ev.get("session_id")
            if not sid:
                continue
            op = ev.get("op")
            if op == "start":
                out[sid] = ev.get("data", {})
            elif op == "touch" and sid in out:
                out[sid]["last_activity_utc"] = ev.get("ts_utc")
            elif op == "end" and sid in out:
                out.pop(sid, None)
    with _lock:
        _sessions = out


_load_sessions_from_disk()


def session_start(session_id: str, user: str, ip: str, user_agent: str) -> None:
    geo = geolocate(ip)
    now = _utc_iso()
    data = {
        "session_id": session_id,
        "user": user,
        "ip": ip or "",
        "country": geo.get("country", ""),
        "region": geo.get("region", ""),
        "city": geo.get("city", ""),
        "isp": geo.get("isp", ""),
        "user_agent": (user_agent or "")[:300],
        "started_at_utc": now,
        "last_activity_utc": now,
    }
    with _lock:
        _sessions[session_id] = data
    _append_jsonl(SESSIONS_FILE, {"ts_utc": now, "session_id": session_id, "op": "start", "data": data})


def session_touch(session_id: str) -> None:
    now = _utc_iso()
    with _lock:
        if session_id in _sessions:
            _sessions[session_id]["last_activity_utc"] = now
    _append_jsonl(SESSIONS_FILE, {"ts_utc": now, "session_id": session_id, "op": "touch"})


def session_end(session_id: str) -> None:
    now = _utc_iso()
    with _lock:
        _sessions.pop(session_id, None)
    _append_jsonl(SESSIONS_FILE, {"ts_utc": now, "session_id": session_id, "op": "end"})


def is_session_active(session_id: str) -> bool:
    """True iff session exists AND last_activity is within INACTIVITY_TIMEOUT_S.

    Reloads from disk if the session_id isn't in this worker's memory — handles
    the multi-worker case where worker A created the session and worker B is
    now serving a follow-up request.
    """
    with _lock:
        s = _sessions.get(session_id)
    if not s:
        _load_sessions_from_disk()
        with _lock:
            s = _sessions.get(session_id)
    if not s:
        return False
    try:
        last = datetime.fromisoformat(s["last_activity_utc"])
    except (KeyError, ValueError):
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_utc_now() - last) < timedelta(seconds=INACTIVITY_TIMEOUT_S)


def active_sessions() -> list[dict]:
    """All sessions whose last activity is within the inactivity window."""
    cutoff = _utc_now() - timedelta(seconds=INACTIVITY_TIMEOUT_S)
    out: list[dict] = []
    with _lock:
        items = list(_sessions.values())
    for s in items:
        try:
            last = datetime.fromisoformat(s["last_activity_utc"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if last >= cutoff:
            enriched = dict(s)
            enriched["started_at_cst"] = format_cst(s.get("started_at_utc", ""))
            enriched["last_activity_cst"] = format_cst(s.get("last_activity_utc", ""))
            secs_idle = int((_utc_now() - last).total_seconds())
            enriched["idle_seconds"] = secs_idle
            enriched["expires_in_seconds"] = max(0, INACTIVITY_TIMEOUT_S - secs_idle)
            out.append(enriched)
    out.sort(key=lambda r: r.get("last_activity_utc", ""), reverse=True)
    return out


# ---------- read-side analytics --------------------------------------------

def read_events(days: int = 7) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    cutoff = _utc_now() - timedelta(days=days)
    out: list[dict] = []
    with EVENTS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.fromisoformat(ev["ts_utc"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            if ts < cutoff:
                continue
            ev["ts_cst"] = format_cst(ev["ts_utc"])
            out.append(ev)
    out.sort(key=lambda r: r.get("ts_utc", ""), reverse=True)
    return out


def summary(days: int = 7) -> dict[str, Any]:
    events = read_events(days=days)
    logins = [e for e in events if e["event"] == "LOGIN"]
    page_views = [e for e in events if e["event"] == "PAGE_VIEW"]

    # Per-user
    by_user: dict[str, dict] = {}
    for e in events:
        u = e.get("user") or "(unknown)"
        b = by_user.setdefault(u, {"user": u, "logins": 0, "page_views": 0, "last_seen_utc": "", "last_seen_cst": "", "last_ip": "", "last_city": ""})
        if e["event"] == "LOGIN":
            b["logins"] += 1
        if e["event"] == "PAGE_VIEW":
            b["page_views"] += 1
        ts = e.get("ts_utc", "")
        if ts > b["last_seen_utc"]:
            b["last_seen_utc"] = ts
            b["last_seen_cst"] = e.get("ts_cst", "")
            b["last_ip"] = e.get("ip", "")
            b["last_city"] = ", ".join([p for p in (e.get("city"), e.get("region"), e.get("country")) if p])

    # Top pages
    page_counts: dict[str, int] = {}
    for e in page_views:
        p = e.get("path", "")
        if not p:
            continue
        page_counts[p] = page_counts.get(p, 0) + 1
    top_pages = sorted(
        [{"path": k, "views": v} for k, v in page_counts.items()],
        key=lambda r: r["views"],
        reverse=True,
    )[:20]

    # Geo distribution (by country)
    geo_counts: dict[str, int] = {}
    for e in events:
        c = e.get("country") or ""
        if not c:
            continue
        geo_counts[c] = geo_counts.get(c, 0) + 1
    by_country = sorted(
        [{"country": k, "events": v} for k, v in geo_counts.items()],
        key=lambda r: r["events"],
        reverse=True,
    )

    return {
        "window_days": days,
        "now_cst": format_cst(_utc_iso()),
        "totals": {
            "events": len(events),
            "logins": len(logins),
            "page_views": len(page_views),
            "unique_users": len(by_user),
            "active_sessions": len(active_sessions()),
        },
        "by_user": sorted(by_user.values(), key=lambda r: r["last_seen_utc"], reverse=True),
        "top_pages": top_pages,
        "by_country": by_country,
    }
