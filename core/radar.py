"""Radar: Dispatch's own job hunt. Searches job boards and company career sites for roles that fit you."""
import hashlib
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from . import store, applications as A
from .discover import search as board_search, _mk, _text, similarity
from .enrich import SESSION
from .extract import parse_relative, norm_date

from . import target as T
from . import boards as BD
from .discover import PROVIDERS


# ---------------------------------------------------------------- profile (learned from your applications)
def default_profile():
    cfg = store.load_settings()
    p = T.profile({**cfg, "radar_queries": "", "radar_locations": ""})
    return {"queries": p["roles"], "locations": [a["label"] for a in p["areas"]] + (["Remote"] if p["remote"] else [])}


def profile(cfg=None):
    return T.profile(cfg or store.load_settings())


# ---------------------------------------------------------------- LinkedIn public job search (no login, no key)
def linkedin_search(roles, location, remote=False, log=None, extra=""):
    """Past-24-hours postings for any of `roles` near `location` (or US remote)."""
    from bs4 import BeautifulSoup
    out = []
    for i in range(0, len(roles), 5):
        kw = " OR ".join(f'"{r}"' for r in roles[i:i + 5])
        if extra:
            kw = f"({kw}) AND ({extra})"
        params = {"keywords": kw, "location": "United States" if remote else location, "f_TPR": "r86400", "start": 0}
        if remote:
            params["f_WT"] = "2"
        else:
            params["distance"] = "50"
        r = SESSION.get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search", params=params, timeout=20)
        if r.status_code == 429:
            raise RuntimeError("rate-limited")
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.base-card") or soup.select("li")
        seen_ids = {j["id"] for j in out}
        for card in cards:
            urn = card.get("data-entity-urn") or ""
            m = re.search(r"jobPosting:(\d+)", urn)
            link = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            if not m and link:
                m = re.search(r"-(\d{6,})(?:\?|$)", link.get("href", "")) or re.search(r"/jobs/view/(?:[^/?]*-)?(\d{6,})", link.get("href", ""))
            if not m:
                continue
            jid = m.group(1)
            if "li:" + jid in seen_ids:
                continue
            seen_ids.add("li:" + jid)
            g = lambda sel: (card.select_one(sel).get_text(" ", strip=True) if card.select_one(sel) else "")
            title = g("h3.base-search-card__title") or g("h3")
            if not title:
                continue
            tm = card.select_one("time")
            j = _mk("LinkedIn", title, g("h4.base-search-card__subtitle") or g("h4"), g("span.job-search-card__location"),
                    f"https://www.linkedin.com/jobs/view/{jid}/", tm.get("datetime") if tm else None, "")
            j["id"] = "li:" + jid  # same id as LinkedIn alert emails, so nothing shows twice
            sal = g("span.job-search-card__salary-info")
            if sal:
                from .extract import parse_salary
                sv = parse_salary(sal)
                if sv:
                    j.update(salary_min=sv["min"], salary_max=sv["max"], salary_period=sv["period"], salary_text=sal)
            j["needs_details"] = True
            out.append(j)
        import time as _t
        _t.sleep(1.2)  # be polite
    return out


# ---------------------------------------------------------------- company career sites
def parse_board(url):
    """Recognize a company careers URL -> (kind, params) or None."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith("http"):
        if ":" in u:  # shorthand like greenhouse:stripe
            kind, slug = u.split(":", 1)
            return (kind.strip().lower(), {"slug": slug.strip()})
        return None
    p = urlparse(u)
    host, parts = p.netloc.lower(), [x for x in p.path.split("/") if x]
    m = re.match(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com", host)
    if m:
        parts = [x for x in parts if not re.match(r"^[a-z]{2}-[A-Z]{2}$", x)]
        if parts:
            return ("workday", {"tenant": m.group(1), "wd": m.group(2), "site": parts[0]})
    if "greenhouse.io" in host and parts:
        slug = parts[0] if parts[0] not in ("embed", "v1") else (re.search(r"for=([\w-]+)", p.query) or [None, None])[1]
        return ("greenhouse", {"slug": slug}) if slug else None
    if host.endswith("lever.co") and parts:
        return ("lever", {"slug": parts[0]})
    if "ashbyhq.com" in host and parts:
        return ("ashby", {"slug": parts[0]})
    if "smartrecruiters.com" in host and parts:
        return ("smartrecruiters", {"slug": parts[0]})
    return None


def board_label(kind, prm):
    return f"{kind}:{prm.get('slug') or prm.get('tenant') + '/' + prm.get('site')}"


def watched_boards(cfg):
    boards = {}
    for line in re.split(r"[\n,]", cfg.get("watch_companies") or ""):
        b = parse_board(line)
        if b:
            boards[board_label(*b)] = (b[0], b[1], None)
    if cfg.get("watch_auto", True):
        for a in A.all_apps():
            b = parse_board(a.get("link"))
            if b:
                boards.setdefault(board_label(*b), (b[0], b[1], a.get("company")))
    return boards


def _words(s):
    return {w[:5] for w in re.findall(r"[a-z+#]+", (s or "").lower()) if w not in {"the", "and", "of", "for", "a", "sr", "senior", "jr", "ii", "iii", "i"}}


def title_fits(title, queries):
    return T.role_fit(title, queries) is not None


def _workday(prm, queries, company):
    base = f"https://{prm['tenant']}.{prm['wd']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{prm['tenant']}/{prm['site']}"
    out = {}
    for q in queries:
        r = SESSION.post(api + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q}, timeout=15,
                         headers={"Accept": "application/json", "Content-Type": "application/json"})
        for jp in (r.json().get("jobPostings") or []):
            if title_fits(jp.get("title"), queries):
                out[jp["externalPath"]] = jp
    jobs = []
    for path, jp in list(out.items())[:12]:
        desc, posted, loc = "", parse_relative(jp.get("postedOn") or ""), jp.get("locationsText")
        try:
            d = SESSION.get(api + path, timeout=15, headers={"Accept": "application/json"}).json().get("jobPostingInfo", {})
            desc = _text(d.get("jobDescription", ""))
            posted = norm_date(d.get("startDate")) or posted
            loc = d.get("location") or loc
        except Exception:
            pass
        jobs.append(_mk(company or prm["tenant"].title(), jp.get("title"), company or prm["tenant"].title(), loc,
                        f"{base}/{prm['site']}{path}", posted, desc))
    return jobs


def _greenhouse(prm, queries, company):
    r = SESSION.get(f"https://boards-api.greenhouse.io/v1/boards/{prm['slug']}/jobs?content=true", timeout=20)
    jobs = []
    for d in r.json().get("jobs", []):
        if title_fits(d.get("title"), queries):
            import html
            jobs.append(_mk(company or prm["slug"].title(), d["title"], company or prm["slug"].title(), (d.get("location") or {}).get("name"),
                            d.get("absolute_url"), d.get("first_published") or d.get("updated_at"), _text(html.unescape(d.get("content", "")))))
    return jobs


def _lever(prm, queries, company):
    r = SESSION.get(f"https://api.lever.co/v0/postings/{prm['slug']}?mode=json", timeout=20)
    jobs = []
    for d in r.json():
        if title_fits(d.get("text"), queries):
            sr = d.get("salaryRange") or {}
            created = datetime.fromtimestamp(d["createdAt"] / 1000, timezone.utc).date().isoformat() if d.get("createdAt") else None
            desc = (d.get("descriptionPlain") or "") + "\n" + "\n".join(_text(l.get("content", "")) for l in d.get("lists", []))
            jobs.append(_mk(company or prm["slug"].title(), d["text"], company or prm["slug"].title(), (d.get("categories") or {}).get("location"),
                            d.get("hostedUrl"), created, desc, sr.get("min"), sr.get("max")))
    return jobs


def _ashby(prm, queries, company):
    r = SESSION.get(f"https://api.ashbyhq.com/posting-api/job-board/{prm['slug']}?includeCompensation=true", timeout=20)
    jobs = []
    for d in r.json().get("jobs", []):
        if title_fits(d.get("title"), queries):
            loc = d.get("location") + (" (Remote)" if d.get("isRemote") and "remote" not in d.get("location", "").lower() else "") if d.get("location") else ("Remote" if d.get("isRemote") else "")
            comp = (d.get("compensation") or {}).get("compensationTierSummary")
            j = _mk(company or prm["slug"].title(), d["title"], company or prm["slug"].title(), loc, d.get("jobUrl"),
                    d.get("publishedAt"), d.get("descriptionPlain") or _text(d.get("descriptionHtml", "")))
            if comp and not j.get("salary_min"):
                from .extract import parse_salary
                s = parse_salary(comp)
                if s:
                    j.update(salary_min=s["min"], salary_max=s["max"], salary_text=comp)
            jobs.append(j)
    return jobs


def _smartrecruiters(prm, queries, company):
    jobs = []
    for q in queries[:3]:
        r = SESSION.get(f"https://api.smartrecruiters.com/v1/companies/{prm['slug']}/postings", params={"q": q, "limit": 20}, timeout=15)
        for d in r.json().get("content", []):
            if title_fits(d.get("name"), queries):
                loc = d.get("location") or {}
                jobs.append(_mk(company or prm["slug"], d["name"], company or (d.get("company") or {}).get("name"),
                                ", ".join(x for x in (loc.get("city"), loc.get("region")) if x) + (" (Remote)" if loc.get("remote") else ""),
                                f"https://jobs.smartrecruiters.com/{prm['slug']}/{d.get('id')}", d.get("releasedDate"), ""))
    return jobs


BOARD_FN = {"workday": _workday, "greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "smartrecruiters": _smartrecruiters}


# ---------------------------------------------------------------- run
def tidy_finds(prof=None):
    """Hide earlier Radar finds that don't fit your current roles and areas."""
    prof = prof or profile()
    n = 0
    for j in store.all_jobs():
        if j.get("radar") and j.get("status") == "discovered":
            why = T.why_not(j, prof)
            if why:
                store.update_meta(j["id"], status="hidden")
                store.upsert_job({"id": j["id"], "hidden_reason": why}, "web")
                n += 1
    return n


def run(progress=None):
    import time as _t
    from .enrich import enrich
    cfg = store.load_settings()
    prof = profile(cfg)
    roles, areas = prof["roles"], prof["areas"]
    log = progress or (lambda m: None)
    resume = set(store.resume_profile(cfg)["skills"])
    report = Counter()
    found = []
    targets = [(a["label"], False) for a in areas] + ([("Remote", True)] if prof["remote"] else [])
    log(f"Radar: {len(roles)} roles in {', '.join(t[0] for t in targets)}")

    # 1) LinkedIn, one area at a time (sequential and gentle)
    li_ok = (cfg.get("radar_sources") or {}).get("LinkedIn", True)
    for label, remote in targets:
        if not li_ok:
            break
        try:
            jobs = linkedin_search(roles, label, remote)
            for j in jobs:
                j["searched_area"] = label
            found.extend(jobs)
            report["LinkedIn"] += len(jobs)
            log(f"Radar: LinkedIn {label}: {len(jobs)} postings")
        except RuntimeError:
            li_ok = False
            report["LinkedIn (paused, too many requests)"] += 1
        except Exception:
            report["LinkedIn unreachable"] += 1

    # 1b) LinkedIn again, aimed at the employers you asked for: credit unions, universities, schools, government
    sources_on = cfg.get("radar_sources") or {}
    on = lambda name: sources_on.get(name, True)
    if li_ok and on("LinkedIn (public sector & credit unions)"):
        sector = '"credit union" OR university OR college OR "school district" OR schools OR county OR "city of" OR "state of"'
        for label, remote in targets:
            if remote:
                continue
            try:
                jobs = linkedin_search(roles[:10], label, False, extra=sector)
                for j in jobs:
                    j["searched_area"] = label
                found.extend(jobs)
                report["LinkedIn (public sector & credit unions)"] += len(jobs)
            except RuntimeError:
                break
            except Exception:
                report["LinkedIn unreachable"] += 1

    # 1c) Government, school, university and tech boards (rotating so each run stays light)
    local = [label for label, remote in targets if not remote]
    per_source = []
    for name, meta in BD.SOURCES.items():
        btasks = []
        if not on(name):
            continue
        if meta.get("states") and all(st in prof["excluded_states"] for st in meta["states"]):
            continue  # e.g. EdJoin lists only California jobs
        if meta["per"] == "role_area":
            btasks += [(name, r, a) for r in roles[:8] for a in local]
        elif meta["per"] == "role":
            btasks += [(name, r, None) for r in roles[:8]]
        elif meta["per"] == "area_all_roles":
            btasks += [(name, roles[:8], a) for a in local]
        if btasks:
            per_source.append(btasks)
    from itertools import zip_longest
    btasks = [t for group in zip_longest(*per_source) for t in group if t]  # mix sources so each run touches all of them
    per_run = int(cfg.get("radar_board_requests") or 40)
    cur = int(store.get_state().get("board_cursor") or 0) % max(1, len(btasks) or 1)
    todo = (btasks[cur:] + btasks[:cur])[:per_run]
    store.set_state(board_cursor=cur + len(todo))

    def run_board(t):
        name, q, area = t
        try:
            js = BD.SOURCES[name]["fn"](q, area)
            for j in js:
                j["searched_area"] = area
                j["board"] = name
            _t.sleep(0.6)
            return name, js
        except Exception:
            return name, None

    if todo:
        log(f"Radar: {len(todo)} searches on GovernmentJobs, SchoolJobs, HigherEdJobs and Dice")
        with ThreadPoolExecutor(max_workers=3) as ex:
            for name, js in ex.map(run_board, todo):
                if js is None:
                    report[f"{name} unreachable"] += 1
                else:
                    report[name] += len(js)
                    found.extend(js)

    # 2) job-board APIs: keyed boards for each area, remote boards for remote
    keyed = [n for n in ("Adzuna", "USAJOBS", "Jooble") if
             {"Adzuna": cfg.get("adzuna_app_id"), "USAJOBS": cfg.get("usajobs_key"), "Jooble": cfg.get("jooble_key")}[n]]
    tasks = [(n, r, label) for n in keyed for r in roles[:6] for label, remote in targets if not remote]
    if prof["remote"] and on("Remote job boards"):
        tasks += [(n, r, "") for n in ("Remotive", "RemoteOK", "The Muse") for r in roles[:6]]
    tasks += [("The Muse", r, label) for r in roles[:4] for label, remote in targets if not remote]

    def board(t):
        name, q, loc = t
        try:
            js = PROVIDERS[name](q, loc, cfg)
            for j in js:
                j["searched_area"] = loc or "Remote"
            return name, js
        except Exception:
            return name, None

    def company(item):
        label, (kind, prm, comp) = item
        try:
            return BOARD_FN[kind](prm, roles, comp)
        except Exception:
            return None

    boards = watched_boards(cfg) if on("Company career sites") else {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for name, js in ex.map(board, tasks):
            if js is None:
                report[f"{name} unreachable"] += 1
            else:
                report[name] += len(js)
                found.extend(js)
        for js in ex.map(company, boards.items()):
            if js is None:
                report["Company sites unreachable"] += 1
            else:
                report["Company career sites"] += len(js)
                for j in js:
                    j["board"] = j.get("board") or "Company site"
                found.extend(js)
    log(f"Radar: {len(found)} postings to check against your roles and areas")

    # 3) keep only what fits you
    applied = {(A.norm_company(a.get("company")), A.norm_title(a.get("title"))) for a in A.all_apps()}
    cutoff = (date.today() - timedelta(days=int(cfg.get("radar_max_age_days") or 14))).isoformat()
    min_match = int(cfg.get("radar_min_match") or 0)
    min_pay = int(cfg.get("radar_min_pay") or 0) * 1000
    existing = {j["id"]: j for j in store.all_jobs()}
    keep, seen, dropped = [], set(), Counter()
    for j in found:
        key = (A.norm_company(j.get("company")), A.norm_title(j.get("title")))
        if not j.get("title") or key in seen:
            continue
        seen.add(key)
        if key in applied:
            dropped["already applied"] += 1; continue
        role = T.role_fit(j["title"], roles, prof["negatives"])
        if not role:
            dropped["not your roles"] += 1; continue
        area = T.area_fit(j.get("location") or "", prof, j.get("searched_area"))
        if not area:
            dropped["outside your areas"] += 1; continue
        if j.get("posted_date") and j["posted_date"] < cutoff:
            dropped["too old"] += 1; continue
        if min_pay and (j.get("salary_max") or j.get("salary_min")) and (j.get("salary_max") or j.get("salary_min")) < min_pay:
            dropped["pay too low"] += 1; continue
        j["target_role"], j["area"] = role, area
        j["employer_type"] = T.employer_type(j.get("company"), j.get("title"), j.get("board"))
        only = cfg.get("radar_only_types") or []
        if only and j["employer_type"] not in only:
            dropped["not a selected employer type"] += 1; continue
        keep.append(j)

    # 4) open new postings for details (skills, requirements, pay, apply link), then score
    fresh = [j for j in keep if j["id"] not in existing]
    for i, j in enumerate([j for j in fresh if j.pop("needs_details", False)][:int(cfg.get("radar_detail_reads") or 40)]):
        enrich(j)
        _t.sleep(0.8)
        if i % 10 == 9:
            log(f"Radar: read {i + 1} new postings")
    out = []
    for j in keep:
        j.pop("needs_details", None)
        if j["id"] in existing and existing[j["id"]].get("skills"):
            j["skills"] = existing[j["id"]]["skills"]
        m = store.match_score(j.get("skills"), list(resume))
        if m is not None and m < min_match:
            dropped["low resume match"] += 1; continue
        j["match"] = m
        favored = cfg.get("radar_favor_types") or ["Credit union", "University / college", "School / district", "Government"]
        j["fit"] = round(0.6 * (m if m is not None else 60) + 40 + (8 if j.get("employer_type") in favored else 0))
        j["fit"] = min(100, j["fit"])
        j["radar"] = 1
        j["radar_found"] = existing.get(j["id"], {}).get("radar_found") or store.now()
        out.append(j)
    out.sort(key=lambda j: (j["fit"], j.get("posted_date") or ""), reverse=True)
    tidy_finds(prof)
    new = [j for j in out if store.upsert_job(j, "web") and j["id"] not in existing]
    rep = {"Sources": {k: v for k, v in report.items()}, "Filtered out": dict(dropped)}
    store.set_state(radar_last=store.now(), radar_report=rep, radar_found=len(out), radar_new=len(new),
                    radar_profile={"roles": roles, "areas": [a["label"] for a in areas], "remote": prof["remote"]},
                    radar_sites=len(boards))
    log(f"Radar: {len(new)} new matches ({len(out)} fit you)")
    return new, rep
