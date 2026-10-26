"""Search public job boards for roles similar to one you already have."""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from .enrich import SESSION, _text
from .extract import analyze, parse_salary, norm_date, salary_label

STOP = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "ii", "iii", "iv", "i", "the", "and", "of", "a",
        "remote", "hybrid", "-", "–", "&", "level", "entry", "mid", "contract", "full", "time", "part", "us", "usa"}


def core_query(title):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    t = re.split(r"\s[-–|,/]\s|\s@\s", t)[0]
    words = [w for w in re.findall(r"[A-Za-z+#.]+", t) if w.lower() not in STOP]
    return " ".join(words[:4]) or (title or "")


def _tokens(s):
    return {w.lower() for w in re.findall(r"[A-Za-z+#]+", s or "") if w.lower() not in STOP and len(w) > 1}


def similarity(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0
    return round(100 * len(ta & tb) / len(ta | tb))


def _mk(source, title, company, location, url, posted=None, desc="", smin=None, smax=None, salary_text=None, period="year"):
    j = {"source": "web", "board": source, "title": (title or "").strip(), "company": (company or "").strip(),
         "location": (location or "").strip(), "url": url, "apply_url": url, "posted_date": norm_date(posted),
         "description": desc, "salary_min": smin, "salary_max": smax, "salary_text": salary_text, "salary_period": period,
         "origin": "web", "enrich_status": "ok"}
    j["id"] = "web:" + hashlib.sha1((url or j["title"] + j["company"]).encode()).hexdigest()[:14]
    return analyze(j)


def _remotive(q, loc, cfg):
    r = SESSION.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(q)}&limit=25", timeout=15)
    out = []
    for d in r.json().get("jobs", [])[:25]:
        sal = parse_salary(d.get("salary") or "")
        out.append(_mk("Remotive", d.get("title"), d.get("company_name"), "Remote · " + (d.get("candidate_required_location") or ""),
                       d.get("url"), d.get("publication_date"), _text(d.get("description", ""))[:15000],
                       sal and sal["min"], sal and sal["max"], d.get("salary") or None, sal["period"] if sal else "year"))
    return out


def _remoteok(q, loc, cfg):
    tag = quote_plus(q.split()[0].lower()) if q else ""
    r = SESSION.get(f"https://remoteok.com/api?tag={tag}", timeout=15)
    out = []
    want = _tokens(q)
    for d in r.json()[1:]:
        if not isinstance(d, dict) or not (_tokens(d.get("position")) & want):
            continue
        out.append(_mk("RemoteOK", d.get("position"), d.get("company"), d.get("location") or "Remote",
                       d.get("apply_url") or d.get("url"), d.get("date"), _text(d.get("description", ""))[:15000],
                       d.get("salary_min") or None, d.get("salary_max") or None))
    return out[:20]


def _themuse(q, loc, cfg):
    cats = []
    ql = q.lower()
    if re.search(r"data|analyst|analytics|bi\b|business intel", ql):
        cats.append("Data and Analytics")
    if re.search(r"engineer|developer|software|backend|frontend|full.?stack", ql):
        cats.append("Software Engineering")
    if re.search(r"\bit\b|support|technician|systems|admin|network", ql):
        cats.append("IT")
    if not cats:
        return []
    url = "https://www.themuse.com/api/public/jobs?page=0&descending=true" + "".join("&category=" + quote_plus(c) for c in cats)
    if loc and "remote" not in loc.lower():
        url += "&location=" + quote_plus(loc)
    r = SESSION.get(url, timeout=15)
    out = []
    want = _tokens(q)
    for d in r.json().get("results", []):
        if not (_tokens(d.get("name")) & want):
            continue
        locs = ", ".join(l.get("name", "") for l in d.get("locations", []))
        out.append(_mk("The Muse", d.get("name"), (d.get("company") or {}).get("name"), locs,
                       (d.get("refs") or {}).get("landing_page"), d.get("publication_date"), _text(d.get("contents", ""))[:15000]))
    return out[:20]


def _adzuna(q, loc, cfg):
    if not (cfg.get("adzuna_app_id") and cfg.get("adzuna_app_key")):
        return []
    url = (f"https://api.adzuna.com/v1/api/jobs/us/search/1?app_id={cfg['adzuna_app_id']}&app_key={cfg['adzuna_app_key']}"
           f"&results_per_page=30&what={quote_plus(q)}&max_days_old=30&content-type=application/json")
    if loc and "remote" not in loc.lower():
        url += "&where=" + quote_plus(loc)
    r = SESSION.get(url, timeout=15)
    out = []
    for d in r.json().get("results", []):
        out.append(_mk("Adzuna", d.get("title"), (d.get("company") or {}).get("display_name"),
                       (d.get("location") or {}).get("display_name"), d.get("redirect_url"), d.get("created"),
                       _text(d.get("description", "")), d.get("salary_min") and round(d["salary_min"]),
                       d.get("salary_max") and round(d["salary_max"])))
    return out


def _usajobs(q, loc, cfg):
    if not (cfg.get("usajobs_key") and cfg.get("usajobs_email")):
        return []
    url = f"https://data.usajobs.gov/api/search?Keyword={quote_plus(q)}&ResultsPerPage=25"
    if loc and "remote" not in loc.lower():
        url += "&LocationName=" + quote_plus(loc)
    r = SESSION.get(url, timeout=15, headers={"Authorization-Key": cfg["usajobs_key"], "User-Agent": cfg["usajobs_email"],
                                               "Host": "data.usajobs.gov"})
    out = []
    for it in r.json().get("SearchResult", {}).get("SearchResultItems", []):
        d = it.get("MatchedObjectDescriptor", {})
        pay = (d.get("PositionRemuneration") or [{}])[0]
        lo, hi = pay.get("MinimumRange"), pay.get("MaximumRange")
        per = "hour" if pay.get("RateIntervalCode") == "PH" else "year"
        mult = 2080 if per == "hour" else 1
        desc = (d.get("QualificationSummary") or "") + "\n\n" + " ".join((d.get("UserArea", {}).get("Details", {}) or {}).get("MajorDuties", []) or [])
        req = (d.get("UserArea", {}).get("Details", {}) or {}).get("RequiredDocuments", "")
        out.append(_mk("USAJOBS", d.get("PositionTitle"), d.get("OrganizationName"), d.get("PositionLocationDisplay"),
                       d.get("PositionURI"), d.get("PublicationStartDate"), desc + "\n\nRequired documents: " + (req or ""),
                       lo and round(float(lo) * mult), hi and round(float(hi) * mult), None, per))
    return out


def _jooble(q, loc, cfg):
    if not cfg.get("jooble_key"):
        return []
    r = SESSION.post(f"https://jooble.org/api/{cfg['jooble_key']}", json={"keywords": q, "location": loc or ""}, timeout=15)
    out = []
    for d in r.json().get("jobs", [])[:30]:
        sal = parse_salary(d.get("salary") or "")
        out.append(_mk("Jooble", d.get("title"), d.get("company"), d.get("location"), d.get("link"), d.get("updated"),
                       _text(d.get("snippet", "")), sal and sal["min"], sal and sal["max"], d.get("salary") or None))
    return out


PROVIDERS = {"Adzuna": _adzuna, "USAJOBS": _usajobs, "Jooble": _jooble, "Remotive": _remotive,
             "RemoteOK": _remoteok, "The Muse": _themuse}


def search(query, location="", cfg=None, ref_title=None):
    """Returns (jobs, report) where report lists per-board results/errors."""
    cfg = cfg or {}
    report = {}
    results = []

    def run(name):
        try:
            return name, PROVIDERS[name](query, location, cfg), None
        except Exception as e:
            return name, [], f"{type(e).__name__}"

    with ThreadPoolExecutor(max_workers=6) as ex:
        for name, jobs, err in ex.map(run, PROVIDERS):
            if err:
                report[name] = "unreachable"
            elif not jobs and name in ("Adzuna", "USAJOBS", "Jooble") and not any(
                    cfg.get(k) for k in {"Adzuna": ["adzuna_app_id"], "USAJOBS": ["usajobs_key"], "Jooble": ["jooble_key"]}[name]):
                report[name] = "add a free key in Settings"
            else:
                report[name] = f"{len(jobs)} found"
            results.extend(jobs)
    seen, uniq = set(), []
    for j in results:
        k = (j["title"].lower(), (j["company"] or "").lower())
        if k in seen or not j["title"]:
            continue
        seen.add(k)
        j["similarity"] = similarity(ref_title or query, j["title"])
        uniq.append(j)
    uniq.sort(key=lambda j: (j["similarity"], j.get("posted_date") or ""), reverse=True)
    return uniq[:60], report


def search_links(query, location=""):
    q, l = quote_plus(query), quote_plus(location or "")
    return [
        {"label": "LinkedIn", "url": f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r604800"},
        {"label": "Indeed", "url": f"https://www.indeed.com/jobs?q={q}&l={l}&fromage=7"},
        {"label": "Google Jobs", "url": f"https://www.google.com/search?q={q}+jobs+{l}&ibp=htl;jobs"},
        {"label": "Glassdoor", "url": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locKeyword={l}"},
        {"label": "ZipRecruiter", "url": f"https://www.ziprecruiter.com/jobs-search?search={q}&location={l}&days=7"},
        {"label": "Dice", "url": f"https://www.dice.com/jobs?q={q}&location={l}&filters.postedDate=SEVEN"},
    ]
