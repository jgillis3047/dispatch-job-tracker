"""Public-sector, education and tech job boards Radar searches (no keys or logins needed).
Formats checked live in October 2026: GovernmentJobs & SchoolJobs (NEOGOV), HigherEdJobs, Dice, EdJoin."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from .discover import _mk
from .enrich import SESSION
from .extract import parse_salary, parse_relative


def _lines(el):
    return [x.strip() for x in el.get_text("\n", strip=True).split("\n") if x.strip()]


def _salary(j, text):
    s = parse_salary(text or "")
    if s:
        j.update(salary_min=s["min"], salary_max=s["max"], salary_period=s["period"], salary_text=s["text"])


# ---------------------------------------------------------------- NEOGOV: GovernmentJobs.com and SchoolJobs.com
def _neogov(host, label, keyword, location):
    url = f"https://www.{host}/jobs?keyword={quote_plus(keyword)}&location={quote_plus(location)}&distance=50"
    r = SESSION.get(url, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return parse_neogov(r.text, host, label)


def parse_neogov(html, host, label):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li.job-item"):
        a = li.select_one("a.job-details-link")
        if not a:
            continue
        for junk in li.select("button, script, [id*=Dialog], .saved-jobs-dialog-overlay"):
            junk.decompose()
        lines = [l for l in _lines(li) if l != a.get_text(strip=True)]
        org, where = li.select_one(".job-organization"), li.select_one(".job-location")
        employer = org.get_text(" ", strip=True) if org else (lines[0] if lines else "")
        loc = where.get_text(" ", strip=True) if where else (lines[1] if len(lines) > 1 else "")
        loc = re.sub(r"^(?:City of|County of|Town of)\s+(?=[A-Z][\w .'-]+,\s*[A-Z]{2}\b)", "", loc)
        loc = loc.split(" - ")[-1] if re.search(r" - [^-]+,\s*[A-Z]{2}\b", loc) else loc
        rest = " ".join(l for l in lines if l not in (employer, loc))
        j = _mk(label, a.get_text(" ", strip=True), employer, loc, urljoin(f"https://www.{host}", a["href"]), None, "")
        j["id"] = f"{host.split('.')[0]}:" + (li.get("data-job-id") or a["href"].split("/")[2])
        _salary(j, rest)
        m = re.search(r"Closes in ([^|]+)", rest)
        if m:
            j["closes_text"] = m.group(1).strip()
        j["needs_details"] = True
        out.append(j)
    return out


def governmentjobs(keyword, location):
    return _neogov("governmentjobs.com", "GovernmentJobs", keyword, location)


def schooljobs(keyword, location):
    return _neogov("schooljobs.com", "SchoolJobs", keyword, location)


# ---------------------------------------------------------------- HigherEdJobs (universities and colleges, nationwide)
def higheredjobs(keyword, location=None):
    url = ("https://www.higheredjobs.com/search/advanced_action.cfm?Keyword=" + quote_plus(keyword) +
           "&PosType=&InstType=&JobCat=&Region=&SubRegion=&Metros=&OnlyTitle=1&SortBy=1&NumJobs=100")
    r = SESSION.get(url, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return parse_hej(r.text)


def parse_hej(html):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href*='details.cfm?JobCode=']"):
        m = re.search(r"JobCode=(\d+)", a["href"])
        title = a.get_text(" ", strip=True)
        if not m or not title or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        box = a
        for _ in range(5):
            box = box.parent
            if box is None or len(box.get_text(" ", strip=True)) > 60:
                break
        lines = [l for l in _lines(box)] if box else []
        lines = [l for l in lines if l != title]
        inst = lines[0] if lines else ""
        loc = lines[1] if len(lines) > 1 else ""
        j = _mk("HigherEdJobs", title, inst, loc, "https://www.higheredjobs.com/search/" + a["href"],
                parse_relative(" ".join(lines)), "")
        j["id"] = "hej:" + m.group(1)
        _salary(j, " ".join(lines[2:]))
        j["needs_details"] = True
        out.append(j)
    return out


# ---------------------------------------------------------------- Dice (tech roles)
def _ago(t):
    t = (t or "").strip().lower()
    if t in ("today", "just now", "new"):
        return datetime.now(timezone.utc).date().isoformat()
    m = re.match(r"(\d+)\s*([hdwm])", t)
    if m:
        unit = {"h": "hour", "d": "day", "w": "week", "m": "month"}[m.group(2)]
        return parse_relative(f"{m.group(1)} {unit}s ago")
    return parse_relative(t)


def dice(keywords, location):
    if isinstance(keywords, (list, tuple)) and len(keywords) > 4:  # Dice rejects long OR searches
        out = []
        for i in range(0, len(keywords), 4):
            try:
                out += dice(keywords[i:i + 4], location)
            except Exception:
                pass
            time.sleep(0.8)
        return out
    q = " OR ".join(f'"{k}"' for k in keywords) if isinstance(keywords, (list, tuple)) else keywords
    url = (f"https://www.dice.com/jobs?q={quote_plus(q)}&location={quote_plus(location + ', USA')}"
           "&radius=50&radiusUnit=mi&filters.postedDate=SEVEN&pageSize=50")
    r = SESSION.get(url, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return parse_dice(r.text)


def parse_dice(html):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for card in soup.select("[data-testid=job-card]"):
        a = card.select_one("a[data-testid=job-search-job-detail-link]") or card.select_one("a[href*='/job-detail/']")
        gid = card.get("data-job-guid") or (re.search(r"/job-detail/([\w-]+)", a["href"]).group(1) if a else None)
        title = a.get_text(" ", strip=True) if a else ""
        if not title or not gid or gid in seen:
            continue
        seen.add(gid)
        comp = card.select_one("[data-testid=job-card-company-name]")
        loc, when = "", ""
        for p in card.find_all("p"):
            t = p.get_text(" ", strip=True)
            if "•" in t:
                loc, _, when = (x.strip() for x in t.partition("•"))
                break
        j = _mk("Dice", title, comp.get_text(strip=True) if comp else "", loc, "https://www.dice.com/job-detail/" + gid, _ago(when), "")
        j["id"] = "dice:" + gid
        sal = card.select_one("#salary-label")
        if sal and re.search(r"\d{2}", sal.get_text()):
            _salary(j, sal.get_text(" ", strip=True).replace("USD", "$").replace("per hour", "/hr"))
        if "remote" in loc.lower():
            j["work_style"] = "Remote"
        j["needs_details"] = True
        out.append(j)
    return out


# ---------------------------------------------------------------- EdJoin (California schools only)
def edjoin(keyword, location=None):
    url = ("https://www.edjoin.org/Home/LoadJobs?rows=50&page=1&sort=postingDate&sortVal=0&order=desc&keywords=" + quote_plus(keyword) +
           "&location=&searchType=all&regions=&jobTypes=&days=0&empType=&catID=0&onlineApps=&recruitmentCenterID=0"
           "&stateID=0&regionID=0&districtID=0&searchID=0")
    r = SESSION.get(url, timeout=20, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    data = r.json().get("data") or []
    out = []
    for d in data:
        ms = re.search(r"\d+", d.get("postingDate") or "")
        posted = datetime.fromtimestamp(int(ms.group(0)) / 1000, timezone.utc).date().isoformat() if ms else None
        loc = ", ".join(x for x in (d.get("city"), "CA" if d.get("stateName") == "California" else d.get("stateName")) if x)
        j = _mk("EdJoin", d.get("positionTitle"), d.get("districtName"), loc,
                f"https://www.edjoin.org/Home/JobPosting/{d.get('postingID')}", posted, "")
        j["id"] = f"edjoin:{d.get('postingID')}"
        _salary(j, f"{d.get('PayRangeFrom') or ''} - {d.get('PayRangeTo') or ''} {d.get('PayRangeDropdown') or ''}")
        out.append(j)
    return out


# ---------------------------------------------------------------- Indeed (blocks automated search) -> email alert links
def alert_links(roles, areas, remote=False):
    """Pre-filled searches on each site, ready for one click on 'Create alert'."""
    top = roles[:4]
    qor = " OR ".join(f'"{r}"' for r in top)
    sites = {
        "Glassdoor": lambda a: f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={quote_plus(top[0])}&locKeyword={quote_plus(a)}&fromAge=3",
        "ZipRecruiter": lambda a: f"https://www.ziprecruiter.com/jobs-search?search={quote_plus(top[0])}&location={quote_plus(a)}&radius=50&days=5",
        "Dice": lambda a: f"https://www.dice.com/jobs?q={quote_plus(qor)}&location={quote_plus(a + ', USA')}&radius=50&radiusUnit=mi",
        "GovernmentJobs": lambda a: f"https://www.governmentjobs.com/jobs?keyword={quote_plus(top[0])}&location={quote_plus(a)}&distance=50",
        "SchoolJobs": lambda a: f"https://www.schooljobs.com/jobs?keyword={quote_plus(top[0])}&location={quote_plus(a)}&distance=50",
        "HigherEdJobs": lambda a: f"https://www.higheredjobs.com/search/advanced_action.cfm?Keyword={quote_plus(top[0])}",
    }
    how = {"Glassdoor": "Click Create job alert", "ZipRecruiter": "Click Get new jobs by email", "Dice": "Click Save search, turn on email alerts",
           "GovernmentJobs": "Click Save this search, choose daily emails", "SchoolJobs": "Click Save this search, choose daily emails",
           "HigherEdJobs": "Click Save as Job Agent"}
    out = []
    for name, fn in sites.items():
        targets = [areas[0]] if name == "HigherEdJobs" else areas
        out.append({"site": name, "how": how[name], "links": [{"label": a if name != "HigherEdJobs" else "Nationwide", "url": fn(a)} for a in targets]})
    return out


def indeed_alert_links(roles, areas, remote=False):
    q = "(" + " or ".join(f'"{r}"' for r in roles[:6]) + ")"
    links = [{"label": a, "url": f"https://www.indeed.com/jobs?q={quote_plus(q)}&l={quote_plus(a)}&radius=50&fromage=3"} for a in areas]
    if remote:
        links.append({"label": "Remote", "url": f"https://www.indeed.com/jobs?q={quote_plus(q)}&l=Remote&fromage=3"})
    return links


SOURCES = {
    "GovernmentJobs": {"fn": governmentjobs, "per": "role_area", "note": "Cities, counties, states, agencies and many colleges"},
    "SchoolJobs": {"fn": schooljobs, "per": "role_area", "note": "School districts, colleges and education service districts"},
    # HigherEdJobs blocks automated readers (Incapsula bot wall, checked Oct 2026), so it isn't searched.
    "Dice": {"fn": dice, "per": "area_all_roles", "note": "Tech and data roles"},
    "EdJoin": {"fn": edjoin, "per": "role", "note": "California schools only", "states": ["CA"]},
}
