"""Read emails over IMAP (Gmail by default; Outlook/Yahoo/iCloud work with their app passwords)."""
import imaplib
import re
from datetime import datetime, timedelta

IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
}
SMTP_HOSTS = {"imap.gmail.com": "smtp.gmail.com", "outlook.office365.com": "smtp.office365.com",
              "imap.mail.yahoo.com": "smtp.mail.yahoo.com", "imap.mail.me.com": "smtp.mail.me.com"}

ALERT_SENDERS = ["linkedin.com", "indeed.com", "ziprecruiter.com", "glassdoor.com", "dice.com", "monster.com",
                 "simplyhired.com", "careerbuilder.com", "joinhandshake.com", "wellfound.com", "builtin.com",
                 "usajobs.gov", "lensa.com", "jobright.ai", "talent.com", "jooble.org", "snagajob.com", "governmentjobs.com", "schooljobs.com",
                 "higheredjobs.com", "neogov.com", "google.com"]
ALERT_SUBJECTS = ["job alert", "jobs for you", "new jobs", "jobs matching", "recommended jobs", "is hiring", "job matches"]
STATUS_SUBJECTS = ["application", "applying", "applied", "candidacy", "interview", "next steps", "offer", "position", "thank you"]


class MailError(Exception):
    pass


def imap_host(email_addr, override=None):
    if override:
        return override
    domain = (email_addr or "").split("@")[-1].lower()
    return IMAP_HOSTS.get(domain, "imap." + domain)


def smtp_host(email_addr, override=None):
    h = imap_host(email_addr, override)
    return SMTP_HOSTS.get(h, h.replace("imap", "smtp", 1))


def connect(email_addr, password, host=None):
    host = imap_host(email_addr, host)
    try:
        M = imaplib.IMAP4_SSL(host, 993, timeout=30)
    except Exception as e:
        raise MailError(f"Couldn't reach {host}. Check your internet connection. ({e})")
    try:
        M.login(email_addr, (password or "").replace(" ", ""))
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "Application-specific password" in msg or "AUTHENTICATIONFAILED" in msg or "Invalid credentials" in msg:
            raise MailError(f"{email_addr}: sign-in rejected. Use a 16-character App Password (not your normal password) "
                            "from myaccount.google.com/apppasswords, and make sure IMAP is on in Gmail settings.")
        raise MailError(f"{email_addr}: sign-in failed: {msg}")
    return M


def _select_all_mail(M, is_gmail):
    if is_gmail:
        typ, boxes = M.list()
        for b in boxes or []:
            line = b.decode(errors="ignore")
            if "\\All" in line:
                name = line.split(' "/" ')[-1].strip()
                if M.select(name, readonly=True)[0] == "OK":
                    return name
    M.select("INBOX", readonly=True)
    return "INBOX"


def _gm_quote(q):
    return '"' + q.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fetch(account, kind, days, extra_senders=None, limit=500, progress=None, seen=None):
    """Yield raw message bytes. kind = 'alerts' or 'status'. `seen(message_id)` lets us skip already-read mail cheaply."""
    from .status import STATUS_QUERY
    email_addr, pw, host = account["email"], account.get("app_password"), account.get("imap_host") or None
    M = connect(email_addr, pw, host)
    is_gmail = "gmail" in imap_host(email_addr, host)
    try:
        box = _select_all_mail(M, is_gmail)
        senders = ALERT_SENDERS + [s.strip() for s in (extra_senders or []) if s.strip()]
        if is_gmail:
            if kind == "alerts":
                q = (f"newer_than:{int(days)}d ({' OR '.join('from:' + s for s in senders)} OR "
                     f"subject:({' OR '.join(chr(34) + s + chr(34) for s in ALERT_SUBJECTS)}))")
            else:
                q = f"newer_than:{int(days)}d -category:promotions -category:social {STATUS_QUERY}"
            typ, data = M.uid("SEARCH", "X-GM-RAW", _gm_quote(q))
            if typ != "OK":
                raise MailError("Gmail search failed.")
            uids = data[0].split()
        else:
            since = (datetime.now() - timedelta(days=int(days))).strftime("%d-%b-%Y")
            uids = set()
            terms = [("FROM", s) for s in senders] + [("SUBJECT", s) for s in ALERT_SUBJECTS] if kind == "alerts" \
                else [("SUBJECT", s) for s in STATUS_SUBJECTS]
            for key, val in terms:
                typ, data = M.uid("SEARCH", None, "SINCE", since, key, f'"{val}"')
                if typ == "OK":
                    uids.update(data[0].split())
            uids = sorted(uids, key=int)
        uids = uids[-limit:]
        if progress:
            progress(f"{email_addr}: {len(uids)} {'alert' if kind == 'alerts' else 'application'} emails to check")
        todo = list(reversed(uids))
        if seen and todo:
            keep = []
            for i in range(0, len(todo), 100):
                chunk = b",".join(todo[i:i + 100])
                typ, data = M.uid("FETCH", chunk, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                for item in data or []:
                    if not isinstance(item, tuple):
                        continue
                    m = re.search(rb"UID (\d+)", item[0])
                    mid = re.search(rb"Message-ID:\s*(<[^>]+>)", item[1] or b"", re.I)
                    if m and not (mid and seen(mid.group(1).decode(errors="ignore"))):
                        keep.append(m.group(1))
            todo = keep
            if progress:
                progress(f"{email_addr}: {len(todo)} new to read")
        for i, uid in enumerate(todo, 1):
            typ, data = M.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK = never marks mail as read
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            if progress and i % 15 == 0:
                progress(f"{email_addr}: reading {i} of {len(todo)}")
            yield data[0][1]
    finally:
        try:
            M.logout()
        except Exception:
            pass


def test_login(email_addr, password, host=None):
    M = connect(email_addr, password, host)
    M.logout()
    return True
