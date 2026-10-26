"""Classify application-update emails and pull out the company and role they're about."""
import re
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr

from bs4 import BeautifulSoup

# ordered by precedence when several match
RULES = [
    ("offer", re.compile(r"pleased to (?:extend|offer)|offer letter|extend (?:you )?(?:an|a|the) (?:formal |verbal )?offer|offer of employment|"
                         r"we(?:'d| would) like to offer you", re.I)),
    ("rejected", re.compile(
        r"unfortunately|regret to inform|not (?:be )?mov(?:e|ing) forward|(?:decided|chosen|elected) to (?:move forward|proceed|pursue|go)(?: forward)? with (?:other|another|a different)|"
        r"other candidates|another candidate|not (?:been )?selected|will not be (?:moving|proceeding|advancing|considering)|"
        r"no longer (?:being )?(?:under )?consider|position has (?:been|now been) filled|decided not to (?:proceed|move|pursue)|"
        r"not (?:a|the right) (?:fit|match) (?:at this time|for this)|after careful (?:consideration|review)[^.]{0,80}(?:not|other)|"
        r"we are unable to offer you|have filled (?:the|this) position|not to advance your|declined your application", re.I)),
    ("interview", re.compile(
        r"schedule (?:a |an |your )?(?:time|interview|call|phone|video|meeting|conversation|chat)|invite you to (?:an? )?(?:interview|phone|video|meet)|"
        r"(?:phone|video|virtual|onsite|on-site|technical|first[- ]round|second[- ]round|final[- ]round) (?:screen|interview)|"
        r"interview (?:invitation|request|confirmation|scheduled)|like to (?:speak|chat|talk|meet|connect) with you|"
        r"your availability|calendly\.com|goodtime\.io|select a time|book a time|next (?:step|round)s? in (?:our|the) (?:hiring|interview|selection) process|"
        r"move you forward to|advance you to the next", re.I)),
    ("assessment", re.compile(r"hirevue|codility|hackerrank|codesignal|testgorilla|criteria corp|complete (?:an?|the|your) (?:online )?(?:assessment|questionnaire|skills test)|"
                              r"assessment (?:invitation|link)", re.I)),
    ("withdrawn", re.compile(r"(?:position|requisition|posting|job) (?:has been |was )?(?:closed|cancell?ed|withdrawn|put on hold)|"
                             r"no longer (?:accepting|hiring for|available)", re.I)),
    ("received", re.compile(
        r"thank(?:s| you) for (?:applying|your application|submitting|your interest in (?:the|our|joining|working|a career)|considering)|"
        r"(?:we(?:'ve| have)?|has been|was) (?:successfully )?received|application (?:has been |was )?(?:received|submitted|sent|complete)|"
        r"your application (?:was sent|to|for)|you(?:'ve| have) (?:successfully )?applied|application confirmation|"
        r"we got your application|indeed application:|successfully submitted", re.I)),
]

ATS_DOMAINS = re.compile(r"myworkday|workday|greenhouse|lever\.co|icims|smartrecruiters|ashbyhq|jobvite|taleo|successfactors|paycom|"
                         r"peopleadmin|applytojob|breezy|bamboohr|workable|recruitee|jazzhr|ultipro|ukg|adp\.com|oraclecloud|"
                         r"njoyn|teamtailor|rippling|indeed|linkedin|ziprecruiter|glassdoor|dice|gmail|outlook|hotmail|yahoo|"
                         r"governmentjobs|neogov|usajobs|hire\.|careers\.|talent\.|recruit|noreply|no-reply|mail\.|email\.|e\.|"
                         r"selectminds|avature|phenom|eightfold|cornerstone|csod|clearcompany|paylocity|dayforce|ceridian|isolved", re.I)
NAME_NOISE = re.compile(r"\b(?:talent acquisition|talent team|recruiting(?: team)?|recruitment|careers?|hiring team|hr team|human resources|"
                        r"people (?:team|ops|operations)|team|jobs|notifications?|no[- ]?reply|do not reply|donotreply|workday|via indeed|"
                        r"greenhouse|lever|icims|smartrecruiters|hr|usd|the|at|from|inc\.?|llc|corp\.?)\b", re.I)

STATUS_QUERY = (
    '(subject:(application OR applying OR applied OR candidacy OR interview OR "next steps" OR offer OR position OR role OR opportunity OR "thank you") '
    'OR from:(myworkday.com OR greenhouse.io OR lever.co OR icims.com OR smartrecruiters.com OR ashbyhq.com OR jobvite.com OR taleo.net '
    'OR successfactors.com OR paycomonline.net OR peopleadmin.com OR applytojob.com OR breezy.hr OR bamboohr.com OR workablemail.com '
    'OR indeedapply.com OR governmentjobs.com OR ultipro.com OR rippling.com OR dayforcehcm.com OR paylocity.com))'
)


def message_text(msg):
    html = text = None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            body = part.get_content()
        except Exception:
            continue
        ct = part.get_content_type()
        if ct == "text/plain" and text is None:
            text = body
        elif ct == "text/html" and html is None:
            html = body
    if html and (not text or len(text) < 80):
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["style", "script", "head"]):
            t.decompose()
        text = soup.get_text("\n", strip=True)
    return re.sub(r"[ \t ‌]+", " ", text or "")


def _clean_company(s):
    s = re.sub(r"[\"“”]", "", s or "")
    s = NAME_NOISE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -–|,:.!")
    return s if 2 <= len(s) <= 60 else None


def _clip(s):
    s = re.split(r"\s(?:at|with|in|located|has|have|was|is|-|–|\|)\s|[.!,;\n(]", s.strip(), maxsplit=1)[0]
    s = s.strip(" -–\"“”'")
    return s if 3 <= len(s) <= 90 and len(s.split()) <= 12 else None


TITLE_RX = [
    re.compile(r"for the position(?: of)?:?\s+([A-Z][\w/&,()'.+# -]{2,80}?)(?:[.!\n]| at | with |$)"),
    re.compile(r"(?:about|regarding|discuss) (?:the|your|our) ([A-Z][\w/&,()'.+# -]{2,80}?) (?:position|role|opening|job|opportunity)", re.I),
    re.compile(r"(?:the )?position of ([A-Z][\w/&,()'.+# -]{2,80}?) (?:at|with|in|for) ", re.I),
    re.compile(r"your application (?:to|for) (?:the )?(.+?) (?:position |role |job )?at ([A-Z][\w&.,' -]{1,50})", re.I),
    re.compile(r"(?:for|to) the (?:position of |role of )?([A-Z][\w/&,()'.+# -]{2,80}?) (?:position|role|opening|job|opportunity|req)", re.I),
    re.compile(r"application (?:for|to) (?:the )?(?:position of )?([A-Z][\w/&,()'.+# -]{2,80})", re.I),
    re.compile(r"indeed application:\s*(.+)", re.I),
    re.compile(r"(?:position|role|job title|requisition)\s*[:\-]\s*([^\n]{3,80})", re.I),
]
COMPANY_RX = [
    re.compile(r"(?:applying|application|interest|applied)\s+(?:to|at|with|in)\s+(?:a (?:career|position|role) (?:at|with) )?([A-Z][\w&.' -]{1,50}?)(?:[.!,\n]| for | and | has | was | is | -|$)"),
    re.compile(r"(?:position|role|opportunity|job) (?:at|with) ([A-Z][\w&.' -]{1,50}?)(?:[.!,\n]| and |$)"),
    re.compile(r"(?:team|everyone|all of us) at ([A-Z][\w&.' -]{1,50}?)(?:[.!,\n]|$)"),
    re.compile(r"your application was sent to ([A-Z][\w&.' -]{1,50})", re.I),
]


PLATFORM = re.compile(r"^(?:apply|indeed(?: apply| application)?|government ?jobs|schooljobs|self[- ]service|notify|my ?workday|workday|https?|www|"
                      r"linkedin|ziprecruiter|glassdoor|greenhouse|lever|icims|smartrecruiters|jobvite|taleo|successfactors|paycom|"
                      r"careers?|talent|recruiting|recruitment|no ?reply|do not reply|hiring|applicant|candidate|human resources|hr|"
                      r"jobs?|team|notifications?|support|admin|info|mail|email|system|application|you|we|us|our)$", re.I)
ORG_WORD = re.compile(r"\b(?:inc|llc|ltd|corp|co|company|group|university|college|school|district|bank|credit|union|county|city|state|"
                      r"health|healthcare|hospital|medical|clinic|systems|solutions|services|technologies|technology|tech|labs?|partners|"
                      r"insurance|federal|department|energy|entertainment|capital|financial|foundation|institute|center|centre|council|"
                      r"agency|authority|association|industries|international|global|holdings|consulting|software|games|studios|"
                      r"airlines?|motors|pharma|logistics|networks|communications|media|resorts?|casino|realty|homes|housing|port|"
                      r"office|board|ventures|capital|bancorp|trust|cooperative|enterprises?)\b", re.I)
ROLE_WORD = re.compile(r"\b(?:analyst|engineer|developer|scientist|specialist|administrator|manager|coordinator|architect|technician|"
                       r"director|consultant|associate|programmer|lead|officer|steward|partner|auditor|agent|intern|assistant|designer|"
                       r"representative|supervisor|strategist|accountant|controller|advisor|expert|owner|head|planner|researcher|"
                       r"tester|admin)\b", re.I)


def valid_company(c, sender_addr=""):
    if not c:
        return None
    c = re.split(r"\s+(?:has|have|was|is|for|and|regarding|about|via|using|through)\s+|\s*@|\bEmail\b", c, maxsplit=1)[0]
    c = re.sub(r"^(?:my ?workday|workday|indeed)\s+", "", c, flags=re.I).strip(" -–|,:.!()")
    if not c or len(c) < 2 or PLATFORM.match(c):
        return None
    if ROLE_WORD.search(c) and (not ORG_WORD.search(c) or ROLE_WORD.search(c.split()[-1])):
        return None  # that's a job title, not a company
    return c


def looks_like_person(name, addr=""):
    """A recruiter writing from their own address, e.g. 'Scott Kaplan <scott.kaplan@...>'."""
    w = (name or "").replace(",", " ").split()
    if not (2 <= len(w) <= 3 and all(re.fullmatch(r"[A-Z][a-z'\-]+\.?", x) for x in w)) or ORG_WORD.search(name):
        return False
    local, _, dom = (addr or "").lower().partition("@")
    if re.search(r"myworkday|workday|greenhouse|lever|icims|smartrecruiters|ashby|jobvite|taleo|successfactors|paycom|"
                 r"peopleadmin|ultipro|ukg|adp|oraclecloud|governmentjobs|neogov|indeed|linkedin|ziprecruiter|breezy|bamboohr|workable", dom):
        return False  # sent through a hiring system, so the display name is the company
    return any(len(x) > 2 and x.lower().strip(".") in local for x in w)


def valid_title(t):
    if not t:
        return None
    t = re.sub(r"^(?:our|the|your|a|an|for|of)\s+", "", t.strip(), flags=re.I).strip(" -–\"“”'")
    if not t or not t[0].isupper() and not t[0].isdigit() and not t.isupper():
        return None
    if re.match(r"(?i)^(position|role|job|following|create|this|requisition|career|opening)\b", t):
        return None
    return t if ROLE_WORD.search(t) or re.search(r"(?i)\b(?:analytics|data|it|support|operations|systems)\b", t) and len(t.split()) >= 2 else None


def _domain_company(addr):
    dom = (addr or "").split("@")[-1].lower()
    if not dom or ATS_DOMAINS.search(dom):
        return None
    parts = [p for p in dom.split(".") if p not in ("com", "org", "net", "io", "co", "us", "edu", "gov", "careers", "jobs", "mail",
                                                     "email", "hr", "talent", "recruiting", "k12", "ca", "wa", "nv", "pa", "state")]
    return parts[-1].replace("-", " ").title() if parts else None


def extract_company_title(sender_name, sender_addr, subject, body):
    title = company = None
    head = f"{subject}\n{body[:2500]}"
    # Indeed: "Indeed Application: <title>", with the company on the line after the title in the body
    m = re.search(r"indeed application:\s*(.+)", subject or "", re.I)
    if m:
        title = valid_title(_clip(m.group(1)) or m.group(1).strip())
        if title:
            mm = re.search(re.escape(title[:40]) + r"[^\n]*\n+\s*([^\n]{2,80})", body)
            if mm:
                company = valid_company(re.split(r"\s+[-–·|]\s+", mm.group(1))[0], sender_addr)
    if not title:
        for rx in TITLE_RX:
            m = rx.search(head)
            if m:
                title = valid_title(_clip(m.group(1)))
                if m.lastindex and m.lastindex >= 2 and not company:
                    company = valid_company(_clean_company(_clip(m.group(2)) or ""), sender_addr)
                if title:
                    break
    m = re.search(r"your application was sent to ([^\n]+)\n+\s*([^\n]{3,90})", body, re.I)
    if m:
        company = company or valid_company(_clean_company(m.group(1)))
        title = title or valid_title(_clip(m.group(2)))
    if not company:
        for rx in COMPANY_RX:
            for mm in rx.finditer(head):
                company = valid_company(_clean_company(mm.group(1)), sender_addr)
                if company:
                    break
            if company:
                break
    if not company and not looks_like_person(sender_name, sender_addr):
        company = valid_company(_clean_company(sender_name), sender_addr)
    if not company:
        company = valid_company(_domain_company(sender_addr) or "")
    return company, title


def classify(subject, body):
    text = f"{subject}\n{body[:6000]}"
    hits = [kind for kind, rx in RULES if rx.search(text)]
    if not hits:
        return None
    kind = hits[0]
    # "thank you for your interest ... unfortunately" -> rejected already wins by order.
    # Interview language inside a rejection ("we interviewed many candidates") shouldn't flip it.
    if kind == "interview" and "rejected" in hits:
        kind = "rejected"
    return kind


def snippet_for(kind, body):
    rx = dict(RULES).get(kind)
    m = rx.search(body) if rx else None
    if not m:
        return re.sub(r"\s+", " ", body[:200]).strip()
    a, b = max(0, m.start() - 120), min(len(body), m.end() + 160)
    return ("…" if a else "") + re.sub(r"\s+", " ", body[a:b]).strip() + ("…" if b < len(body) else "")


def parse_status_email(raw_bytes, alert_parser=None):
    """Return an event dict or None if the email isn't an application update."""
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    subject = str(msg.get("Subject", "") or "")
    name, addr = parseaddr(str(msg.get("From", "")))
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
    except Exception:
        dt = None
    body = message_text(msg)
    if re.search(r"job alert|jobs? (?:for you|you may|matching)|new jobs|recommended jobs|is hiring|top job picks|jobs near", subject, re.I):
        return None
    if re.search(r"(?i)newsletter|webinar|unsubscribe from this list", subject):
        return None
    kind = classify(subject, body)
    if not kind:
        return None
    # a "received" match needs to look like it's actually about an application
    if kind == "received" and not re.search(r"(?i)appl(?:y|ied|ying|ication)|candida", subject + body[:1500]):
        return None
    company, title = extract_company_title(name, addr, subject, body)
    return {"message_id": msg.get("Message-ID", "") or f"{addr}|{subject}|{msg.get('Date')}", "kind": kind,
            "date": dt.isoformat() if dt else None, "subject": subject, "sender": addr, "sender_name": name,
            "company_guess": company, "title_guess": title, "snippet": snippet_for(kind, body)[:400],
            "text": body[:5000]}
