"""Open a job posting and pull structured details (JSON-LD JobPosting, LinkedIn guest API, page text)."""
import html as htmllib
import json
import re
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from .extract import parse_salary, parse_relative, norm_date, analyze, work_style

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})


def _text(html_fragment):
    if not html_fragment:
        return ""
    soup = BeautifulSoup(html_fragment, "html.parser")
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4"]):
        br.insert_before("\n")
    t = soup.get_text()
    t = htmllib.unescape(t)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t ]+", " ", t)).strip()


def _jsonld_jobposting(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "{}")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return d
                stack.extend(d.get("@graph", []) if isinstance(d.get("@graph"), list) else [])
            elif isinstance(d, list):
                stack.extend(d)
    return None


def _from_jsonld(jp, job):
    job["title"] = job.get("title") or jp.get("title")
    org = jp.get("hiringOrganization")
    if isinstance(org, dict) and org.get("name"):
        job["company"] = job.get("company") or org["name"]
    if jp.get("datePosted"):
        job["posted_date"] = norm_date(jp["datePosted"])
    if jp.get("validThrough"):
        job["closes_date"] = norm_date(jp["validThrough"])
    locs = jp.get("jobLocation")
    locs = locs if isinstance(locs, list) else [locs] if locs else []
    names = []
    for l in locs:
        a = (l or {}).get("address", {}) if isinstance(l, dict) else {}
        if isinstance(a, dict):
            parts = [a.get("addressLocality"), a.get("addressRegion")]
            n = ", ".join(p for p in parts if p)
            if n:
                names.append(n)
    if str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        job["work_style"] = "Remote"
        names = names or ["Remote"]
    if names and not job.get("location"):
        job["location"] = " / ".join(dict.fromkeys(names))[:120]
    bs = jp.get("baseSalary") or jp.get("estimatedSalary")
    if isinstance(bs, list):
        bs = bs[0] if bs else None
    if isinstance(bs, dict):
        v = bs.get("value", {})
        unit = (v.get("unitText") if isinstance(v, dict) else bs.get("unitText")) or "YEAR"
        lo = v.get("minValue") or v.get("value") if isinstance(v, dict) else v
        hi = v.get("maxValue") if isinstance(v, dict) else None
        try:
            lo = float(lo) if lo else None
            hi = float(hi) if hi else None
            mult = {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12}.get(str(unit).upper(), 1)
            if lo:
                job["salary_min"], job["salary_max"] = round(lo * mult), round(hi * mult) if hi else None
                job["salary_period"] = "hour" if str(unit).upper() == "HOUR" else "year"
                job["salary_text"] = f"${lo:,.0f}" + (f" – ${hi:,.0f}" if hi else "") + f" / {str(unit).lower()}"
        except (TypeError, ValueError):
            pass
    if jp.get("employmentType"):
        et = jp["employmentType"]
        job["employment_type"] = ", ".join(et) if isinstance(et, list) else str(et)
    desc = _text(jp.get("description", ""))
    if desc and len(desc) > len(job.get("description") or ""):
        job["description"] = desc
    return job


def _linkedin(job_id, job):
    r = SESSION.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}", timeout=15)
    if r.status_code != 200:
        return False
    soup = BeautifulSoup(r.text, "html.parser")
    g = lambda sel: (soup.select_one(sel).get_text(" ", strip=True) if soup.select_one(sel) else None)
    job["title"] = job.get("title") or g("h2.top-card-layout__title")
    job["company"] = job.get("company") or g("a.topcard__org-name-link") or g(".topcard__flavor")
    loc = g(".topcard__flavor--bullet")
    if loc:
        job["location"] = loc
    posted = g(".posted-time-ago__text")
    if posted:
        job["posted_date"] = parse_relative(posted) or job.get("posted_date")
    applicants = g(".num-applicants__caption")
    if applicants:
        job["applicants"] = applicants
    sal = g(".compensation__salary") or g(".salary")
    if sal:
        s = parse_salary(sal)
        if s:
            job.update(salary_min=s["min"], salary_max=s["max"], salary_period=s["period"], salary_text=sal)
    desc = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    if desc:
        job["description"] = _text(str(desc))
    for li in soup.select(".description__job-criteria-item"):
        h, v = li.select_one("h3"), li.select_one("span")
        if h and v:
            k = h.get_text(strip=True).lower()
            if "employment" in k:
                job["employment_type"] = v.get_text(strip=True)
            elif "seniority" in k:
                job["seniority"] = v.get_text(strip=True)
    code = soup.select_one("code#applyUrl")
    if code:
        m = re.search(r'"(https?://[^"]+)"', code.decode_contents())
        if m:
            u = htmllib.unescape(m.group(1))
            q = parse_qs(urlparse(u).query)
            job["apply_url"] = unquote(q["url"][0]) if q.get("url") else u
            job["apply_type"] = "Company site"
    else:
        job["apply_type"] = job.get("apply_type") or "LinkedIn"
    return True


def enrich(job: dict) -> dict:
    """Best-effort: never raises. Sets job['enrich_status']."""
    url = job.get("url") or job.get("apply_url")
    status = "ok"
    try:
        m = re.search(r"linkedin\.com/jobs/view/(\d+)", url or "")
        if m and _linkedin(m.group(1), job):
            pass
        elif url:
            r = SESSION.get(job.get("apply_url") or url, timeout=15, allow_redirects=True)
            final = r.url
            if r.status_code >= 400 or len(r.text) < 500:
                status = f"blocked ({r.status_code})" if r.status_code in (401, 403, 429) else f"unavailable ({r.status_code})"
            else:
                if not re.search(r"(click|track|cts|engage|links?)\.", urlparse(final).netloc):
                    job["apply_url"] = final
                soup = BeautifulSoup(r.text, "html.parser")
                jp = _jsonld_jobposting(soup)
                if jp:
                    _from_jsonld(jp, job)
                else:
                    for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                        t.decompose()
                    main = soup.find("main") or soup.find(attrs={"id": re.compile("job|description", re.I)}) or soup.body
                    txt = _text(str(main)) if main else ""
                    if len(txt) > 300:
                        job["description"] = txt[:20000]
                    else:
                        status = "no details on page"
                    tm = soup.find("time")
                    if tm and tm.get("datetime") and not job.get("posted_date"):
                        job["posted_date"] = norm_date(tm["datetime"])
                    if not job.get("posted_date"):
                        job["posted_date"] = parse_relative(soup.get_text(" ")[:20000])
        else:
            status = "no link"
    except requests.RequestException as e:
        status = "unreachable"
    except Exception as e:  # parsing surprises shouldn't kill a sync
        status = f"error: {type(e).__name__}"
    job["enrich_status"] = status
    analyze(job)
    if not job.get("work_style"):
        job["work_style"] = work_style(job.get("location"), job.get("description", "")[:3000])
    return job
