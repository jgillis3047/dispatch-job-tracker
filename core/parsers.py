"""Turn job-alert emails into job records."""
import hashlib
import re
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr
from urllib.parse import urlparse, parse_qs, unquote

from bs4 import BeautifulSoup

from .extract import parse_salary, looks_like_location, parse_relative, work_style

SOURCES = {
    "linkedin": ("LinkedIn", r"linkedin\.com"),
    "indeed": ("Indeed", r"indeed\.com"),
    "ziprecruiter": ("ZipRecruiter", r"ziprecruiter\.com"),
    "glassdoor": ("Glassdoor", r"glassdoor\.com"),
    "dice": ("Dice", r"dice\.com"),
    "monster": ("Monster", r"monster\.com"),
    "simplyhired": ("SimplyHired", r"simplyhired\.com"),
    "careerbuilder": ("CareerBuilder", r"careerbuilder\.com"),
    "handshake": ("Handshake", r"joinhandshake\.com|handshake"),
    "wellfound": ("Wellfound", r"wellfound\.com|angel\.co"),
    "builtin": ("Built In", r"builtin\.com"),
    "usajobs": ("USAJOBS", r"usajobs\.gov"),
    "governmentjobs": ("GovernmentJobs", r"governmentjobs\.com|neogov"),
    "schooljobs": ("SchoolJobs", r"schooljobs\.com"),
    "higheredjobs": ("HigherEdJobs", r"higheredjobs\.com"),
    "lensa": ("Lensa", r"lensa\.com"),
    "jobright": ("Jobright", r"jobright\.ai"),
    "google": ("Google", r"google\.com"),
}

# links that point at a single posting
JOB_LINK_RX = [
    ("linkedin", re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?]*-)?(\d{6,})", re.I)),
    ("indeed", re.compile(r"indeed\.com/(?:rc/clk|viewjob|pagead/clk|m/viewjob|applystart|.*jk=)", re.I)),
    ("indeed", re.compile(r"cts\.indeed\.com|engage\.indeed\.com/f/a/", re.I)),
    ("ziprecruiter", re.compile(r"ziprecruiter\.com/(?:k/|ekm/|c/|job/|jobs/|km/)", re.I)),
    ("glassdoor", re.compile(r"glassdoor\.com/(?:partner/jobListing|job-listing|Job/|jobs/)", re.I)),
    ("dice", re.compile(r"dice\.com/job-detail|dice\.com/jobs/detail", re.I)),
    ("monster", re.compile(r"monster\.com/job-openings|monster\.com/jobs/", re.I)),
    ("usajobs", re.compile(r"usajobs\.gov/(?:job|GetJob)/", re.I)),
    ("governmentjobs", re.compile(r"governmentjobs\.com/(?:careers/[\w-]+/)?jobs/\d+", re.I)),
    ("schooljobs", re.compile(r"schooljobs\.com/(?:careers/[\w-]+/)?jobs/\d+", re.I)),
    ("higheredjobs", re.compile(r"higheredjobs\.com/.*details\.cfm\?JobCode=", re.I)),
    ("builtin", re.compile(r"builtin\.com/job/", re.I)),
    ("wellfound", re.compile(r"wellfound\.com/jobs/\d", re.I)),
    ("generic", re.compile(r"greenhouse\.io|lever\.co|myworkdayjobs\.com|smartrecruiters|icims\.com|jobvite|ashbyhq|bamboohr\.com/careers|/careers?/.*\d|/jobs?/.*\d", re.I)),
]

BOILERPLATE = re.compile(
    r"^(avatar|create|log ?in|sign ?in|view( all)?( similar)?( jobs?)?|see (all|more)( jobs)?|apply( now)?|easy apply|unsubscribe|manage|settings|"
    r"privacy|help|learn more|search|edit|save|more jobs|view job|see jobs|show more|get the app|"
    r"view details|see details|view (this )?job|jobs? (alert|for you)|click here|open|here|new|promoted|actively recruiting|"
    r"be an early applicant|.*matches your (preferences|alert)|top applicant|this company is actively hiring|\d+ (connections?|alumni|applicants?).*)$",
    re.I)
NOISE_LINE = re.compile(r"^(easy apply|promoted|actively recruiting|be an early applicant|new|urgently hiring|responsive employer|"
                        r"\d+ (school alumni|connections?|applicants?).*|.*ago|apply now|view job|view similar.*|top applicant|"
                        r"your profile matches.*|·|\||.*\bjob alert\b.*|.*matches your preferences.*)$", re.I)


def detect_source(sender: str, html: str = "") -> str:
    s = (sender or "").lower()
    for key, (_, rx) in SOURCES.items():
        if re.search(rx, s):
            return key
    return "other"


def source_label(key):
    return SOURCES.get(key, ("Email",))[0] if key in SOURCES else ("Web" if key == "web" else "Email")


def canonical_url(url: str):
    """Return (canonical_url, external_id)."""
    url = (url or "").strip()
    m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?]*-)?(\d{6,})", url, re.I)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/", "li:" + m.group(1)
    q = parse_qs(urlparse(url).query)
    if "indeed.com" in url and q.get("jk"):
        jk = q["jk"][0]
        return f"https://www.indeed.com/viewjob?jk={jk}", "in:" + jk
    for p in ("url", "u", "dest", "redirect", "target"):
        if q.get(p) and q[p][0].startswith("http"):
            return canonical_url(unquote(q[p][0]))
    m = re.search(r"usajobs\.gov/(?:job|GetJob/ViewDetails)/(\d+)", url, re.I)
    if m:
        return f"https://www.usajobs.gov/job/{m.group(1)}", "usa:" + m.group(1)
    return url, None


def job_key(source, ext_id, title, company):
    if ext_id:
        return ext_id
    base = f"{(title or '').lower().strip()}|{(company or '').lower().strip()}"
    return source[:2] + ":" + hashlib.sha1(base.encode()).hexdigest()[:14]


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" ‌ \t·|-–")


def _container_lines(a, title, all_job_hrefs):
    """Walk up from the anchor to the smallest block holding this job's details only."""
    node = a
    best = None
    for _ in range(8):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            break
        hrefs = {canonical_url(x.get("href", ""))[0] for x in node.find_all("a", href=True)} & all_job_hrefs
        if len(hrefs) > 1:
            break
        text = node.get_text("\n", strip=True)
        if len(text) > 900:
            break
        best = node
    if best is None:
        return []
    lines = []
    for raw in best.get_text("\n", strip=True).split("\n"):
        for part in re.split(r"\s+[·•|]\s+", raw):
            p = _clean(part)
            if p and p.lower() != (title or "").lower() and len(p) < 140:
                lines.append(p)
    return lines


RATING = re.compile(r"^\d(?:\.\d)?\s*★?$|^★|^\(|^\)$|^glassdoor est\.?$|^avatar$|^easy apply$", re.I)
ROLEISH = re.compile(r"\b(?:analyst|engineer|developer|scientist|specialist|administrator|manager|coordinator|architect|technician|"
                     r"director|consultant|associate|programmer|lead|officer|steward|auditor|designer|supervisor|admin|analytics)\b", re.I)


def _card_from_anchor(anchors):
    """One link that holds a whole job card (Glassdoor): company, rating, title, location, pay."""
    for a in anchors:
        lines = [_clean(x) for x in a.get_text("\n", strip=True).split("\n")]
        lines = [l for l in lines if l and not RATING.match(l)]
        if len(lines) < 3:
            continue
        t_idx = next((i for i, l in enumerate(lines) if ROLEISH.search(l) and not looks_like_location(l)), None)
        if t_idx is None:
            continue
        loc = next((l for l in lines[t_idx + 1:] if looks_like_location(l)), None)
        pay = next((l for l in lines if parse_salary(l)), None)
        company = lines[t_idx - 1] if t_idx > 0 else None
        return {"title": lines[t_idx], "company": company, "location": loc, "salary_text": pay}
    return None


def _pick_title(anchors):
    texts = [_clean(a.get_text(" ", strip=True)) for a in anchors]
    texts = [t for t in texts if t and not BOILERPLATE.match(t) and 3 <= len(t) <= 120 and len(t.split()) <= 16]
    if not texts:
        imgs = [a.find("img") for a in anchors]
        alts = [_clean(i.get("alt", "")) for i in imgs if i is not None]
        texts = [t for t in alts if t and not BOILERPLATE.match(t)]
    return max(texts, key=len) if texts else None


def _assign_fields(lines, job):
    company = location = None
    rest = []
    for ln in lines:
        if NOISE_LINE.match(ln):
            rel = parse_relative(ln)
            if rel and not job.get("posted_date"):
                job["posted_date"] = rel
            continue
        sal = parse_salary(ln)
        if sal and not job.get("salary_text") and len(ln) < 80:
            job["salary_text"] = sal["text"]
            job["salary_min"], job["salary_max"], job["salary_period"] = sal["min"], sal["max"], sal["period"]
            continue
        if location is None and looks_like_location(ln):
            location = ln
            continue
        if company is None and len(ln) <= 70 and not re.search(r"[.!?]$", ln) and not ln.lower().startswith(("http", "your", "we ", "this ")):
            company = ln
            continue
        rest.append(ln)
    job["company"] = job.get("company") or company
    job["location"] = job.get("location") or location
    snippet = " ".join(rest)[:400]
    if snippet:
        job["email_snippet"] = snippet
    return job


def parse_html_alert(html, source, email_date=None):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["style", "script", "head"]):
        t.decompose()
    groups = {}  # canonical url -> [anchors]
    order = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(rx.search(href) for _, rx in JOB_LINK_RX) and not re.search(
                r"unsubscribe|/settings|/preferences|/help|rjtRedirect|emailSettings|/Job/[^?]*SRCH|/member/|/profile/", href, re.I):
            cu, _ = canonical_url(href)
            if cu not in groups:
                order.append(cu)
            groups.setdefault(cu, []).append(a)
    # Fallback for tracking-link-only emails: links with title-like text
    fallback = not groups
    if fallback:
        for a in soup.find_all("a", href=True):
            t = _clean(a.get_text(" ", strip=True))
            if (a["href"].startswith("http") and t and 2 <= len(t.split()) <= 12 and not BOILERPLATE.match(t)
                    and not re.search(r"unsubscribe|privacy|help|settings|preferences|terms|app\.|apps\.apple|play\.google", a["href"], re.I)):
                cu, _ = canonical_url(a["href"])
                if cu not in groups:
                    order.append(cu)
                groups.setdefault(cu, []).append(a)
    all_hrefs = set(groups)
    jobs = []
    for cu in order:
        anchors = groups[cu]
        card = _card_from_anchor(anchors)
        title = card["title"] if card else _pick_title(anchors)
        if not title:
            continue
        _, ext = canonical_url(anchors[0]["href"])
        job = {"title": title, "url": cu, "apply_url": cu if ext else anchors[0]["href"], "source": source}
        if card:
            job.update({k: v for k, v in card.items() if v and k != "title"})
            if card.get("salary_text"):
                sal = parse_salary(card["salary_text"])
                if sal:
                    job["salary_min"], job["salary_max"], job["salary_period"] = sal["min"], sal["max"], sal["period"]
        else:
            lines = _container_lines(anchors[0], title, all_hrefs)
            _assign_fields(lines, job)
        if (fallback or source == "other") and not (job.get("location") or job.get("salary_text")):
            continue  # a random link, not a job card
        job["external_id"] = ext
        jobs.append(job)
    return jobs


_TXT_LINK = re.compile(r"^\s*(.+?)\s+<?(https?://[^\s>]+)>?\s*$")


def parse_bullet_text(text, source):
    """ZipRecruiter-style text alerts: 'Title <url>' then 'Company • City, ST • Remote' then pay."""
    lines = [l.rstrip() for l in (text or "").replace("\r", "").split("\n")]
    jobs = []
    for i, l in enumerate(lines):
        m = _TXT_LINK.match(l)
        if not m or BOILERPLATE.match(_clean(m.group(1))) or re.match(r"(?i)^(apply now|view details|view more jobs)$", m.group(1).strip()):
            continue
        nxt = [x.strip() for x in lines[i + 1:i + 6] if x.strip()]
        if not nxt or "•" not in nxt[0]:
            continue
        parts = [p.strip() for p in nxt[0].split("•")]
        company = parts[0]
        loc = parts[1] if len(parts) > 1 else ""
        mode = parts[2] if len(parts) > 2 else ""
        if re.fullmatch(r"[A-Z]{2}", loc) and mode.lower().startswith("remote"):
            loc = "Remote"
        elif mode.lower().startswith(("remote", "hybrid")):
            loc = f"{loc} ({mode.split()[0].title()})"
        cu, ext = canonical_url(m.group(2))
        job = {"title": _clean(m.group(1)), "company": company, "location": loc, "url": cu, "apply_url": m.group(2),
               "source": source, "external_id": ext}
        if len(nxt) > 1:
            sal = parse_salary(nxt[1])
            if sal:
                job.update(salary_text=nxt[1], salary_min=sal["min"], salary_max=sal["max"], salary_period=sal["period"])
        jobs.append(job)
    return jobs


def parse_text_alert(text, source):
    bullet = parse_bullet_text(text, source)
    if len(bullet) >= 2:
        return bullet
    jobs = []
    blocks = re.split(r"\n\s*\n", text or "")
    for b in blocks:
        urls = re.findall(r"https?://\S+", b)
        job_urls = [u for u in urls if any(rx.search(u) for _, rx in JOB_LINK_RX)]
        if not job_urls:
            continue
        lines = [_clean(x) for x in b.splitlines() if x.strip() and not x.strip().startswith("http")]
        lines = [l for l in lines if l and not BOILERPLATE.match(l)]
        if not lines:
            continue
        cu, ext = canonical_url(job_urls[0])
        job = {"title": lines[0], "url": cu, "apply_url": job_urls[0], "source": source, "external_id": ext}
        _assign_fields(lines[1:], job)
        jobs.append(job)
    return jobs


def parse_message(raw_bytes):
    """Parse one RFC822 message -> (meta, [jobs])."""
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    sender = msg.get("From", "")
    subject = str(msg.get("Subject", ""))
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
    except Exception:
        dt = None
    html = text = None
    for part in msg.walk():
        ct = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            body = part.get_content()
        except Exception:
            continue
        if ct == "text/html" and html is None:
            html = body
        elif ct == "text/plain" and text is None:
            text = body
    source = detect_source(sender)
    jobs = parse_html_alert(html, source, dt) if html else []
    if text:
        tjobs = parse_text_alert(text, source)
        good = lambda js: sum(1 for j in js if j.get("company") and j.get("title") and len(j["title"]) < 120 and "http" not in j["title"])
        if good(tjobs) > good(jobs):
            jobs = tjobs
    meta = {"message_id": msg.get("Message-ID", "") or f"{sender}|{subject}|{msg.get('Date')}",
            "sender": parseaddr(sender)[1] or sender, "subject": subject,
            "date": dt.isoformat() if dt else None, "source": source}
    for j in jobs:
        j["email_subject"] = subject
        j["email_date"] = meta["date"]
        j["work_style"] = work_style(j.get("location"), j.get("title"))
        j["id"] = job_key(source, j.get("external_id"), j.get("title"), j.get("company"))
    return meta, jobs
