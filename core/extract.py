"""Text analysis: pull salary, skills, requirements, work style and dates out of job text."""
import re
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- skills
# display name -> regex (case-insensitive). Word-boundary aware.
_SKILL_PATTERNS = {
    # languages
    "Python": r"python", "SQL": r"sql", "R": r"(?<![\w-])R(?![\w-])(?=[,/ ]|\s(?:programming|language|studio))",
    "JavaScript": r"javascript|\bjs\b", "TypeScript": r"typescript", "Java": r"java(?!\s*script)",
    "C#": r"c#|c\s?sharp", "C++": r"c\+\+", "Go": r"golang", "Scala": r"scala", "VBA": r"vba",
    "HTML": r"html5?", "CSS": r"css3?", "Bash": r"bash|shell scripting", "PowerShell": r"powershell",
    "SAS": r"\bsas\b", "MATLAB": r"matlab", "Rust": r"\brust\b", "PHP": r"\bphp\b", "Ruby": r"\bruby\b",
    "Swift": r"\bswift\b", "Kotlin": r"kotlin",
    # databases
    "PostgreSQL": r"postgres(?:ql)?", "MySQL": r"mysql", "T-SQL": r"t-sql|tsql", "SQL Server": r"sql server|mssql",
    "Oracle": r"oracle", "Snowflake": r"snowflake", "BigQuery": r"bigquery", "Redshift": r"redshift",
    "MongoDB": r"mongo(?:db)?", "Databricks": r"databricks", "Supabase": r"supabase", "Redis": r"redis",
    "NoSQL": r"nosql", "Stored Procedures": r"stored procedures?", "Data Warehousing": r"data warehous\w*",
    # data / analytics
    "Tableau": r"tableau", "Power BI": r"power\s?bi", "Looker": r"looker", "Excel": r"excel",
    "Spark": r"(?:py)?spark", "PySpark": r"pyspark", "Pandas": r"pandas", "NumPy": r"numpy",
    "Airflow": r"airflow", "dbt": r"\bdbt\b", "ETL": r"etl|elt", "Data Modeling": r"data model(?:l)?ing",
    "Machine Learning": r"machine learning|\bml\b", "Statistics": r"statistic(?:s|al)",
    "A/B Testing": r"a/b test\w*", "Forecasting": r"forecast\w*", "KPI Development": r"\bkpis?\b",
    "Data Visualization": r"data visuali[sz]ation", "Data Governance": r"data governance",
    "Kafka": r"kafka", "SSIS": r"ssis", "SSRS": r"ssrs", "Alteryx": r"alteryx", "Informatica": r"informatica",
    "Google Analytics": r"google analytics", "Salesforce": r"salesforce", "SAP": r"\bsap\b",
    "PeopleSoft": r"peoplesoft", "Workday": r"workday(?! inc)", "HL7": r"hl7", "FHIR": r"fhir", "Epic": r"\bepic\b(?= systems| emr| ehr|,)",
    # cloud / devops
    "AWS": r"aws|amazon web services", "Azure": r"azure", "GCP": r"gcp|google cloud", "Docker": r"docker",
    "Kubernetes": r"kubernetes|k8s", "Terraform": r"terraform", "CI/CD": r"ci\s?/\s?cd", "Git": r"\bgit\b",
    "GitHub": r"github", "GitLab": r"gitlab", "Jira": r"jira", "Linux": r"linux", "Jamf": r"jamf",
    "Active Directory": r"active directory", "Networking": r"networking|tcp/ip", "ServiceNow": r"servicenow",
    # web / apps
    "React": r"react(?:\.js|js)?(?! native)", "React Native": r"react native", "Node.js": r"node(?:\.js|js)",
    "REST APIs": r"rest(?:ful)?\s?apis?|rest services", "GraphQL": r"graphql", "Django": r"django",
    "Flask": r"flask", "FastAPI": r"fastapi", ".NET": r"\.net\b", "Postman": r"postman", "Expo": r"\bexpo\b",
    # practices / soft
    "Agile": r"agile|scrum", "Project Management": r"project management", "Stakeholder Communication": r"stakeholder",
    "UAT": r"\buat\b|user acceptance",
    "Financial Analysis": r"financial analysis|variance analysis|cost-benefit",
}
_SKILL_RX = {name: re.compile(r"(?<![\w#+])(?:" + pat + r")(?![\w#+])", re.I if name != "R" else 0)
             for name, pat in _SKILL_PATTERNS.items()}


def find_skills(text: str) -> list:
    if not text:
        return []
    found = [name for name, rx in _SKILL_RX.items() if rx.search(text)]
    if "PySpark" in found and "Spark" in found:
        found.remove("Spark")
    return found


# ---------------------------------------------------------------- salary
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK])?"
_PER = r"(?:\s*(?:/|per|an|a)\s*(hour|hr|year|yr|annum|annually|month|mo|week|wk)\b)?"
_SAL_RX = re.compile(
    r"(?:USD\s*)?\$\s?" + _NUM + _PER + r"(?:\s*(?:-|–|—|to)\s*(?:USD\s*)?\$?\s?" + _NUM + r")?" + _PER, re.I)


def _to_num(n, k):
    v = float(n.replace(",", ""))
    return v * 1000 if k else v


def _annualize(v, period):
    p = (period or "").lower()
    if p in ("hour", "hr"):
        return v * 2080
    if p in ("month", "mo"):
        return v * 12
    if p in ("week", "wk"):
        return v * 52
    if not p and v < 300:  # bare "$45" is almost always hourly
        return v * 2080
    return v


def parse_salary(text: str):
    """Return dict(min, max, text, period) with annualized numbers, or None."""
    if not text:
        return None
    best = None
    for m in _SAL_RX.finditer(text):
        lo = _to_num(m.group(1), m.group(2))
        hi = _to_num(m.group(4), m.group(5) or m.group(2)) if m.group(4) else None
        period = m.group(3) or m.group(6)
        if hi and not m.group(2) and m.group(5) and lo < 1000:  # "$90 - $120K"
            lo *= 1000
        if lo < 7 or (not period and not hi and lo < 15000 and lo >= 300):
            continue  # "$5 gift card", "$1,000 bonus"
        lo_a, hi_a = _annualize(lo, period), _annualize(hi, period) if hi else None
        if lo_a < 15000 or lo_a > 1_500_000:
            continue
        cand = {"min": round(lo_a), "max": round(hi_a) if hi_a else None,
                "text": m.group(0).strip(), "period": "hour" if (period or "").lower() in ("hour", "hr") or (not period and lo < 300) else "year"}
        if best is None or (cand["max"] and not best["max"]):
            best = cand
            if cand["max"]:
                break
    return best


def salary_label(smin, smax, period="year", raw=None):
    if not smin:
        return raw or ""
    def f(v):
        if period == "hour":
            return f"${v/2080:.0f}"
        return f"${v/1000:.0f}K"
    s = f(smin) + (f"–{f(smax)}" if smax and smax != smin else "")
    return s + ("/hr" if period == "hour" else "")


# ---------------------------------------------------------------- requirements
_REQS = [
    ("cover_letter", "Cover letter", r"cover letter|letter of (?:interest|intent|application)|motivation letter|letter of introduction"),
    ("references", "References", r"(?:professional|three|two|\d|list of|names of|contact information for)\s+(?:professional\s+)?references|references (?:are |will be )?(?:required|requested)|references upon request|provide references|referees"),
    ("portfolio", "Portfolio / work samples", r"portfolio|work samples?|code samples?|github (?:profile|link)"),
    ("writing_sample", "Writing sample", r"writing sample"),
    ("transcripts", "Transcripts", r"transcripts?"),
    ("certification", "Certification", r"certification(?:s)? (?:required|preferred)|certified|\b(?:comptia|a\+|security\+|pmp|cissp|ccna|aws certified)\b"),
    ("assessment", "Skills assessment", r"assessment|technical (?:test|exercise|challenge)|take-home|coding (?:test|challenge)"),
    ("background_check", "Background check", r"background (?:check|screening|investigation)"),
    ("drug_test", "Drug screen", r"drug (?:test|screen)"),
    ("clearance", "Security clearance", r"(?:security|secret|ts/sci|top secret) clearance|clearance required|public trust"),
    ("no_sponsorship", "No visa sponsorship", r"(?:not|unable to|cannot|will not|won't|no)\s+(?:\w+\s+){0,3}sponsor|sponsorship (?:is )?not (?:available|provided)"),
    ("degree_bachelors", "Bachelor's degree", r"bachelor'?s|\bb\.?s\.?\b(?= degree| in)|undergraduate degree|four-year degree"),
    ("degree_masters", "Master's degree", r"master'?s degree|\bm\.?s\.? in\b|\bmba\b"),
]
_REQ_RX = [(k, label, re.compile(p, re.I)) for k, label, p in _REQS]
_OPTIONAL_RX = re.compile(r"optional|not required|encouraged|preferred|if (?:available|applicable)", re.I)
_YEARS_RX = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?(?:\+\s*)?years?(?:'|’)?\s+(?:of\s+)?(?:\w+\s+){0,4}?(?:experience|exp\b)", re.I)


def find_requirements(text: str) -> list:
    """List of {key,label,optional,snippet}."""
    out = []
    if not text:
        return out
    for key, label, rx in _REQ_RX:
        m = rx.search(text)
        if not m:
            continue
        a, b = max(0, m.start() - 90), min(len(text), m.end() + 90)
        snippet = re.sub(r"\s+", " ", text[a:b]).strip()
        s0 = max(text.rfind(c, 0, m.start()) for c in ".!?\n") + 1
        ends = [i for i in (text.find(c, m.end()) for c in ".!?\n") if i != -1]
        window = text[s0: min(ends) if ends else len(text)]
        out.append({"key": key, "label": label, "optional": bool(_OPTIONAL_RX.search(window)),
                    "snippet": ("…" if a else "") + snippet + ("…" if b < len(text) else "")})
    yrs = [int(m.group(1)) for m in _YEARS_RX.finditer(text) if 0 < int(m.group(1)) <= 20]
    if yrs:
        out.append({"key": "experience", "label": f"{min(yrs)}+ years experience", "optional": False, "snippet": ""})
    return out


# ---------------------------------------------------------------- work style / location
def work_style(*texts) -> str:
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"\bhybrid\b", t):
        return "Hybrid"
    if re.search(r"\bremote\b|work from home|wfh|telecommut|anywhere in the u", t):
        return "Remote"
    if re.search(r"\bon[- ]?site\b|in[- ]office|in person", t):
        return "On-site"
    return ""


_LOC_RX = re.compile(r"^(?:[A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+)*,\s?(?:[A-Z]{2}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)(?:\s\d{5})?|Remote|Hybrid|United States|USA|Anywhere)(?:\s*\((?:Remote|Hybrid|On-site)\))?$")
_STATE_RX = re.compile(r",\s?(?:A[LKZR]|C[AOT]|DE|DC|FL|GA|HI|I[DLNA]|K[SY]|LA|M[EDAINSOT]|N[EVHJMYCD]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[TA]|W[AVIY])\b")


def looks_like_location(s: str) -> bool:
    s = s.strip()
    if len(s) > 60:
        return False
    return bool(_LOC_RX.match(s) or _STATE_RX.search(s) or re.search(r"\b(remote|hybrid|on-site)\b", s, re.I) and len(s) < 40)


# ---------------------------------------------------------------- dates
_AGO_RX = re.compile(r"(\d+|an?|one)\s+(minute|hour|day|week|month)s?\s+ago", re.I)


def parse_relative(text: str, ref: datetime = None):
    ref = ref or datetime.now(timezone.utc)
    if not text:
        return None
    if re.search(r"\b(just now|today|just posted)\b", text, re.I):
        return ref.date().isoformat()
    m = _AGO_RX.search(text)
    if not m:
        return None
    n = m.group(1).lower()
    n = 1 if n in ("a", "an", "one") else int(n)
    unit = m.group(2).lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return (ref - delta).date().isoformat()


def norm_date(s):
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return parse_relative(s)


def analyze(job: dict) -> dict:
    """Fill derived fields from description + email text. Mutates and returns job."""
    blob = "\n".join(x for x in (job.get("title"), job.get("description"), job.get("email_snippet")) if x)
    job["skills"] = find_skills(blob)
    job["requirements"] = find_requirements(job.get("description") or "")
    if not job.get("salary_min"):
        sal = parse_salary(job.get("salary_text") or "") or parse_salary(blob)
        if sal:
            job["salary_min"], job["salary_max"] = sal["min"], sal["max"]
            job["salary_period"] = sal["period"]
            job["salary_text"] = job.get("salary_text") or sal["text"]
    job["work_style"] = job.get("work_style") or work_style(job.get("location"), job.get("title"), (job.get("description") or "")[:3000])
    return job
