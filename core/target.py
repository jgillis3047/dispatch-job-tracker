"""Your target: the roles and areas Dispatch looks for, learned from the jobs you've applied to."""
import math
import re
from collections import Counter

from . import store, applications as A

SENIORITY = r"\b(?:sr|senior|jr|junior|lead|principal|staff|associate|chief|head|i{1,3}|iv|v|vi|\d+|level|mid|entry|experienced|expert)\b"
DEFAULT_NEGATIVE = store.DEFAULT_NEGATIVE
NON_US = re.compile(r"\b(?:europe|emea|uk|united kingdom|india|latam|latin america|apac|asia|canada only|philippines|germany|"
                    r"poland|brazil|mexico|argentina|australia|spain|portugal|netherlands|france|ireland|south africa|nigeria|pakistan)\b", re.I)
REMOTE_RX = re.compile(r"\b(?:remote|anywhere|work from home|wfh|telecommute|distributed)\b", re.I)
STATE_NAMES = {v: k for k, v in A.US_STATES.items() if len(k) > 3}


def role_core(title):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    t = re.split(r"\s[-–|/]\s|,|\s–\s|\s-\s|:", t)[0]
    t = re.sub(SENIORITY, " ", t, flags=re.I)
    t = re.sub(r"[^\w&+# ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?i)^it ", "IT ", t)
    return " ".join(w if w.isupper() and len(w) <= 4 else w.capitalize() for w in t.split())


def _toks(s):
    return [w[:5] for w in re.findall(r"[a-z+#&]+", (s or "").lower()) if w not in {"and", "the", "of", "for", "&", "a", "an", "to", "in"}]


ALIASES = {"bi": ["busin", "intel"], "hris": ["hris"], "sql": ["sql"], "it": ["it"]}


DOMAIN = {"data", "analy", "engin", "syste", "busin", "intel", "hris", "it", "datab", "devel", "scien", "sql", "bi", "infor",
          "techn", "netwo", "secur", "softw", "repor", "finan", "opera", "appli", "resea", "integ", "platf", "cloud", "gover", "progr"}


def _good_role(r):
    t = _toks(r)
    return len(t) >= 2 and bool(set(t) & DOMAIN) and not role_fit_negative(r)


def role_fit_negative(title, negatives=DEFAULT_NEGATIVE):
    tl = (title or "").lower()
    return any(re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", tl) for n in [x.strip().lower() for x in negatives.split(",") if x.strip()])


def role_fit(title, roles, negatives=None):
    """Return the target role this title matches, or None."""
    tl = (title or "").lower()
    for n in [x.strip().lower() for x in (negatives or "").split(",") if x.strip()]:
        if re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", tl):
            return None
    tl_tokens = []
    for t in _toks(title):
        tl_tokens += ["busin", "intel"] if t == "bi" else [t]
    for r in roles:
        rt = _toks(r)
        if rt and _in_order(rt, tl_tokens):
            return r
    return None


def _in_order(needle, hay, max_gap=2):
    """True if the role's words appear in the title in the same order, at most `max_gap` words apart."""
    for start, w in enumerate(hay):
        if w != needle[0]:
            continue
        pos, ok = start, True
        for n in needle[1:]:
            nxt = next((i for i in range(pos + 1, min(len(hay), pos + 2 + max_gap)) if hay[i] == n), None)
            if nxt is None:
                ok = False
                break
            pos = nxt
        if ok:
            return True
    return False


# ---------------------------------------------------------------- areas
def _miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def learned(excluded_states=("CA",)):
    """Roles and areas from your application history."""
    apps = A.all_apps()
    roles = Counter(role_core(a.get("title")) for a in apps if a.get("title") and not a["title"].startswith("("))
    role_list = [r for r, n in roles.most_common() if n >= 2 and _good_role(r)][:14]
    if not role_list:
        role_list = ["Data Analyst", "Data Engineer", "Business Systems Analyst", "Business Intelligence Analyst"]
    ex = {s.strip().upper() for s in excluded_states if s.strip()}
    cities = Counter()
    remote = 0
    for a in apps:
        c, st = A.clean_place(a.get("city"), a.get("state"))
        if c in ("Remote", "Anywhere in US"):
            remote += 1
        elif c and st and st not in ex and not c.startswith("Somewhere"):
            cities[(c, st)] += 1
    clusters = []
    for (c, st), n in cities.most_common():
        pt, _ = A.coords(c, st)
        home = None
        for cl in clusters:
            if pt and cl["pt"] and _miles(pt, cl["pt"]) <= 50:
                home = cl
                break
            if not pt and cl["state"] == st and c in cl["members"]:
                home = cl
                break
        if home:
            home["n"] += n
            home["members"].append(c)
            home["mstates"][c] = st
        else:
            clusters.append({"label": f"{c}, {st}", "state": st, "pt": pt, "n": n, "members": [c], "mstates": {c: st}})
    BIG = ["Seattle", "Washington", "New York", "Philadelphia", "Las Vegas", "Chicago", "Baltimore", "Boston", "Detroit", "Denver",
           "Phoenix", "Dallas", "Houston", "Austin", "Atlanta", "Portland", "Minneapolis", "Pittsburgh", "Newark"]
    for cl in clusters:
        big = next((b for b in BIG if b in cl["members"]), None)
        if big:
            cl["label"] = f"{big}, {cl['mstates'][big]}"
            p2, _ = A.coords(big, cl["mstates"][big])
            cl["pt"] = p2 or cl["pt"]
            cl["state"] = cl["mstates"][big]
        cl.pop("mstates")
    areas = [cl for cl in clusters if cl["n"] >= 2][:8]
    return {"roles": role_list, "areas": areas, "remote": remote > 0, "counts": dict(roles), "apps": len(apps)}


def profile(cfg=None):
    cfg = cfg or store.load_settings()
    excl = [s.strip().upper() for s in (cfg.get("radar_exclude_states") or "").split(",") if s.strip()]
    L = learned(excl)
    roles = [x.strip() for x in re.split(r"[\n,]", cfg.get("radar_queries") or "") if x.strip()] or L["roles"]
    area_labels = [x.strip() for x in (cfg.get("radar_locations") or "").split("\n") if x.strip() and x.strip().lower() != "remote"]
    if area_labels:
        areas = []
        for lab in area_labels:
            m = re.match(r"(.+?),\s*([A-Za-z]{2})$", lab)
            c, st = (m.group(1).strip(), m.group(2).upper()) if m else (lab, "")
            pt, _ = A.coords(c, st) if st else (None, False)
            areas.append({"label": lab, "state": st, "pt": pt, "n": 0, "members": [c]})
    else:
        areas = L["areas"]
    areas = [a for a in areas if a["state"] not in excl]
    remote = cfg.get("radar_remote")
    remote = L["remote"] if remote is None else bool(remote)
    return {"roles": roles, "areas": areas, "remote": remote, "excluded_states": excl,
            "negatives": cfg.get("radar_exclude") or DEFAULT_NEGATIVE, "auto_roles": not cfg.get("radar_queries"),
            "auto_areas": not cfg.get("radar_locations"), "learned_from": L["apps"],
            # kept for the older parts of the app that expect these names
            "queries": roles, "locations": [a["label"] for a in areas] + (["Remote"] if remote else [])}


_PAIR = re.compile(r"([A-Z][A-Za-z.'\- ]{1,40}?),\s*([A-Z]{2}|" + "|".join(sorted((k.title() for k in A.US_STATES if len(k) > 3), key=len, reverse=True)) + r")\b")


def area_fit(location, prof, searched_area=None, lenient=False):
    """Return the matching area label ('Remote' for remote roles) or None.
    searched_area: the area a location-targeted search was run for (its results are already local).
    lenient: for email alerts, only reject when a posting is clearly outside your areas."""
    loc = (location or "").strip()
    if not loc:
        return None
    excl = set(prof["excluded_states"])
    pairs = []
    for c, st in _PAIR.findall(loc):
        st = A.US_STATES.get(st.lower(), st.upper())
        pairs.append((c.strip(), st))
    for c, st in pairs:
        if st in excl:
            continue
        pt, _ = A.coords(c, st)
        for a in prof["areas"]:
            if pt and a["pt"] and _miles(pt, a["pt"]) <= 50:
                return a["label"]
            if c.lower() in (m.lower() for m in a["members"]) and st == a["state"]:
                return a["label"]
            if not pt and st == a["state"] and (searched_area == a["label"] or lenient):
                return a["label"]  # same state, city not looked up yet
    low = loc.lower()
    for a in prof["areas"]:  # LinkedIn-style "Greater Seattle Area", "Washington DC-Baltimore Area"
        if ("area" in low or "metro" in low) and any(re.search(r"\b" + re.escape(m.lower()) + r"\b", low) for m in a["members"]):
            return a["label"]
    if lenient and not pairs and not REMOTE_RX.search(loc):
        return "Unknown"  # can't tell from the alert; don't hide it
    if prof["remote"] and (REMOTE_RX.search(loc) or low in ("united states", "usa", "us")):
        if NON_US.search(loc) and not re.search(r"\b(?:us|usa|united states)\b", low):
            return None
        return "Remote"
    return None


def why_not(job, prof, lenient=False):
    if not role_fit(job.get("title"), prof["roles"], prof["negatives"]):
        return "Not one of your target roles"
    loc = job.get("location") or ("Remote" if job.get("work_style") == "Remote" else "")
    if not loc and lenient:
        return None
    if not area_fit(loc, prof, job.get("searched_area"), lenient):
        return "Outside your areas"
    return None


# ---------------------------------------------------------------- employer type
EMPLOYER_TYPES = [
    ("Credit union", r"credit union|\bc\.?u\.?\b$|\bfcu\b|federal credit|\bbecu\b|\bwsecu\b|penfed|navy federal|alliant|psecu|"
                     r"\bsecu\b|teachers federal|police and fire federal"),
    ("University / college", r"universit|college|community college|institute of technology|polytechnic|school of medicine|"
                             r"\bunlv\b|\bunr\b|\bcsun\b|\bsdsu\b|\buw\b|\bupenn\b|penn state|temple|drexel|georgetown|"
                             r"george mason|johns hopkins|rutgers|northwestern|loyola|depaul|\bnshe\b|higher education"),
    ("School / district", r"school district|public schools|\bschools\b|unified|\busd\b|\bisd\b|educational service district|\besd\b|"
                          r"\bpsesd\b|academy|high school|elementary|middle school|board of education|charter school|"
                          r"office of education|county schools|school board|\bk-?12\b"),
    ("Government", r"^city of|^county of|\bcounty\b|^state of|\bstate\b.*(department|agency|office)|department of|\bdept\b|"
                   r"\bauthority\b|^port of|commission|municipal|government|federal|\bagency\b|\btribe\b|tribal|"
                   r"water district|transit|metro\b|police|sheriff|courts?\b|judicial|legislat|\bfbi\b|\bnsa\b|"
                   r"intelligence community|\bseptA\b|amtrak|housing authority|\bva\b medical|u\.s\. "),
    ("Healthcare", r"health|hospital|medical|clinic|kaiser|providence|cancer center|healthcare|\bmed\b"),
]
_ET = [(n, re.compile(p, re.I)) for n, p in EMPLOYER_TYPES]


CONTRACTOR = re.compile(r"\b(?:inc|llc|corp|corporation|services|solutions|technologies|technology|group|consulting|partners|"
                        r"systems|associates|international|holdings|company)\b\.?", re.I)


def employer_type(company, title="", board=""):
    c = company or ""
    if re.search(r"federal|government", c, re.I) and CONTRACTOR.search(c) and not re.search(r"credit union|\bfcu\b", c, re.I):
        return "Private company"  # e.g. Accenture Federal Services, a government contractor
    for n, rx in _ET:
        if rx.search(c):
            return n
    if board in ("SchoolJobs", "EdJoin"):
        return "School / district"
    if board == "HigherEdJobs":
        return "University / college"
    if board == "GovernmentJobs":
        return "Government"
    return "Private company"
