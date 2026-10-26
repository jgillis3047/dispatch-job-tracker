"""Settings file, resume profile and SQLite job store."""
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .extract import find_skills

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "jobs.db"

MASK = "••••••••"
DEFAULT_NEGATIVE = ("assistant, receptionist, intern, internship, sales, account executive, nurse, driver, teacher, tutor, cashier, "
                    "warehouse, recruiter, customer service, call center, marketing, coding tasks, ai training, annotation, "
                    "data entry, clerk, attorney, physician, therapist, professor, adjunct, faculty, instructor, lecturer, pharmacist")
DEFAULTS = {
    "accounts": [{"email": "jordangillis74@gmail.com", "app_password": "", "imap_host": ""}],  # pre-filled; just needs Google's OK
    "days": 14, "status_days": 150, "auto_sync_minutes": 60,
    "extra_senders": "", "resume_path": "", "excel_path": "", "default_location": "Las Vegas, NV",
    "adzuna_app_id": "", "adzuna_app_key": "", "usajobs_key": "", "usajobs_email": "", "jooble_key": "",
    # radar
    "radar_enabled": True, "radar_every_hours": 1, "radar_sources": {}, "radar_favor_types": ["Credit union", "University / college", "School / district", "Government"], "radar_only_types": [], "radar_exclude_states": "CA", "radar_remote": None, "radar_queries": "", "radar_locations": "",
    "radar_min_match": 50, "radar_min_pay": 0, "radar_max_age_days": 14, "radar_exclude": DEFAULT_NEGATIVE,
    "watch_companies": "", "watch_auto": True,
    "alert_email_on": True, "alert_email_to": "", "alert_desktop_on": True,
    "start_with_windows": False,
    # automation
    "followup_days": 10, "ghost_days": 45, "weekly_report_on": True, "auto_mark_applied": True, "auto_filter_alerts": True,
}
SECRET_KEYS = {"adzuna_app_key", "usajobs_key", "jooble_key"}
_lock = threading.RLock()


# ---------------------------------------------------------------- settings
def load_settings():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception:
            pass
    # migrate single-account settings from v1
    if cfg.get("email") and not cfg.get("accounts"):
        cfg["accounts"] = [{"email": cfg["email"], "app_password": cfg.get("app_password", ""), "imap_host": cfg.get("imap_host", "")}]
    cfg["accounts"] = [a for a in cfg.get("accounts") or [] if a.get("email")]
    return cfg


def save_settings(new):
    cfg = load_settings()
    for k, v in new.items():
        if k == "accounts":
            old = {a["email"].lower(): a for a in cfg.get("accounts", [])}
            accts = []
            for a in v or []:
                email = (a.get("email") or "").strip()
                if not email:
                    continue
                pw = a.get("app_password")
                if not pw or pw == MASK:
                    pw = old.get(email.lower(), {}).get("app_password", "")
                accts.append({"email": email, "app_password": pw, "imap_host": (a.get("imap_host") or "").strip()})
            cfg["accounts"] = accts
            continue
        if k not in DEFAULTS:
            continue
        if k in SECRET_KEYS and (v is None or v == MASK):
            continue  # unchanged masked value
        cfg[k] = v
    cfg.pop("email", None); cfg.pop("app_password", None); cfg.pop("imap_host", None)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), "utf-8")
    return cfg


def public_settings():
    cfg = load_settings()
    out = {k: (MASK if k in SECRET_KEYS and v else v) for k, v in cfg.items()}
    out["accounts"] = [{"email": a["email"], "app_password": MASK if a.get("app_password") else "", "imap_host": a.get("imap_host", "")}
                       for a in cfg["accounts"]]
    return out


def connected(cfg=None):
    """Accounts that Google has approved (have an app password)."""
    cfg = cfg or load_settings()
    return [a for a in cfg["accounts"] if a.get("app_password")]


def account_for(email):
    for a in load_settings()["accounts"]:
        if a["email"].lower() == (email or "").lower():
            return a
    return None


STATE_PATH = DATA_DIR / "state.json"


def get_state():
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {}


def set_state(**kw):
    with _lock:
        s = get_state()
        s.update(kw)
        STATE_PATH.write_text(json.dumps(s, indent=2), "utf-8")
        return s


# ---------------------------------------------------------------- resume
_resume_cache = {"path": None, "mtime": None, "skills": [], "name": None}


def find_resume(cfg):
    p = cfg.get("resume_path")
    if p and Path(p).exists():
        return Path(p)
    for folder in (APP_DIR, APP_DIR.parent):
        pdfs = sorted(folder.glob("*.pdf"), key=lambda x: (("resume" not in x.name.lower()), -x.stat().st_mtime))
        if pdfs:
            return pdfs[0]
    return None


def resume_profile(cfg=None):
    cfg = cfg or load_settings()
    path = find_resume(cfg)
    if not path:
        return {"path": None, "skills": [], "name": None}
    mtime = path.stat().st_mtime
    if _resume_cache["path"] == str(path) and _resume_cache["mtime"] == mtime:
        return dict(_resume_cache)
    text = ""
    try:
        from pypdf import PdfReader
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except Exception:
        pass
    _resume_cache.update(path=str(path), mtime=mtime, skills=find_skills(text), name=path.name)
    return dict(_resume_cache)


def match_score(job_skills, resume_skills):
    if not job_skills or not resume_skills:
        return None
    rs = set(resume_skills)
    # treat close cousins as matches
    alias = {"SQL Server": "T-SQL", "T-SQL": "SQL Server", "Spark": "PySpark", "GitHub": "Git", "GitLab": "Git"}
    hit = sum(1 for s in job_skills if s in rs or alias.get(s) in rs)
    return round(100 * hit / len(job_skills))


# ---------------------------------------------------------------- db
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT DEFAULT 'new', notes TEXT DEFAULT '',
  origin TEXT DEFAULT 'email', first_seen TEXT, updated TEXT, similar_to TEXT
);
CREATE TABLE IF NOT EXISTS emails (message_id TEXT PRIMARY KEY, seen TEXT, jobs INTEGER, subject TEXT, sender TEXT);
"""


def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def email_seen(message_id):
    with db() as con:
        return con.execute("SELECT 1 FROM emails WHERE message_id=?", (message_id,)).fetchone() is not None


def mark_email(meta, n):
    with _lock, db() as con:
        con.execute("INSERT OR REPLACE INTO emails VALUES (?,?,?,?,?)",
                    (meta["message_id"], now(), n, meta.get("subject"), meta.get("sender")))


def get_job(jid):
    with db() as con:
        r = con.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return _row(r) if r else None


def _row(r):
    d = json.loads(r["data"])
    d.update(id=r["id"], status=r["status"], notes=r["notes"], origin=r["origin"], first_seen=r["first_seen"],
             updated=r["updated"], similar_to=r["similar_to"])
    return d


def upsert_job(job, origin="email", similar_to=None):
    """Insert or merge. Returns True if new."""
    keep = {k: v for k, v in job.items() if k not in ("status", "notes", "origin", "first_seen", "updated", "similar_to")}
    with _lock, db() as con:
        r = con.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if r:
            old = json.loads(r["data"])
            for k, v in keep.items():
                if v not in (None, "", []) or k not in old:
                    old[k] = v
            seen_in = set(old.get("seen_in", [])) | set(keep.get("seen_in", []))
            old["seen_in"] = sorted(seen_in)
            con.execute("UPDATE jobs SET data=?, updated=? WHERE id=?", (json.dumps(old), now(), job["id"]))
            return False
        con.execute("INSERT INTO jobs (id,data,status,origin,first_seen,updated,similar_to) VALUES (?,?,?,?,?,?,?)",
                    (job["id"], json.dumps(keep), "new" if origin == "email" else "discovered", origin, now(), now(), similar_to))
        return True


def update_meta(jid, status=None, notes=None):
    with _lock, db() as con:
        if status is not None:
            con.execute("UPDATE jobs SET status=?, updated=? WHERE id=?", (status, now(), jid))
        if notes is not None:
            con.execute("UPDATE jobs SET notes=?, updated=? WHERE id=?", (notes, now(), jid))


def all_jobs():
    with db() as con:
        rows = con.execute("SELECT * FROM jobs").fetchall()
    return [_row(r) for r in rows]


def delete_where(origin=None, demo=False):
    with _lock, db() as con:
        if demo:
            con.execute("DELETE FROM jobs WHERE json_extract(data,'$.demo')=1")
            con.execute("DELETE FROM emails WHERE message_id LIKE 'demo-%'")
        elif origin:
            con.execute("DELETE FROM jobs WHERE origin=? AND status='discovered'", (origin,))


def email_stats():
    with db() as con:
        r = con.execute("SELECT COUNT(*) n, MAX(seen) last FROM emails").fetchone()
    return {"emails_read": r["n"], "last_email_scan": r["last"]}
