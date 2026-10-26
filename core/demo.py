"""Sample alert emails (fictional companies) so the dashboard can be explored before Gmail is connected.
They run through the real email parser; only the page-fetch step is replaced with canned descriptions."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

from .parsers import parse_message
from .extract import analyze

D = lambda n: datetime.now(timezone.utc) - timedelta(days=n)

LINKEDIN_HTML = """<html><body><table>
<tr><td><h2>Your job alert for data analyst in Las Vegas, NV</h2></td></tr>
<tr><td><table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc"><img alt="Northwind Lending"></a></td>
<td><a href="https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc">Senior Data Analyst, Servicing Analytics</a>
<p>Northwind Lending · Las Vegas, NV (Hybrid)</p><p>$95K/yr - $120K/yr</p><p>Actively recruiting</p></td></tr></table></td></tr>
<tr><td><table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4011229876/?trackingId=def">Analytics Engineer</a>
<p>Basalt Health Systems · Remote</p><p>Easy Apply</p></td></tr></table></td></tr>
<tr><td><table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4011230001/?trackingId=ghi">BI Developer (Tableau / Power BI)</a>
<p>Desert Ridge Credit Union · Henderson, NV</p><p>$38/hr - $46/hr</p><p>Be an early applicant</p></td></tr></table></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search?keywords=data">See all jobs</a> <a href="https://www.linkedin.com/comm/psettings/email-unsubscribe">Unsubscribe</a></td></tr>
</table></body></html>"""

INDEED_HTML = """<html><body>
<h1>New jobs for "data engineer"</h1>
<table><tr><td>
<a href="https://www.indeed.com/rc/clk?jk=7f3a9c2b11d0e5aa&from=ja">Data Engineer - Healthcare Integrations</a><br>
<span>Silver Pine Medical Group</span><br><span>Remote</span><br><span>$110,000 - $135,000 a year</span><br>
<span>Build HL7 and FHIR pipelines into our Snowflake warehouse...</span></td></tr>
<tr><td><a href="https://www.indeed.com/rc/clk?jk=21bb04ee9c7f4410&from=ja">Database Developer (SQL Server)</a><br>
<span>Mesa Verde County</span><br><span>Las Vegas, NV 89101</span><br><span>$41.20 - $52.75 an hour</span><br>
<span>Maintain T-SQL stored procedures and SSRS reports...</span></td></tr>
<tr><td><a href="https://www.indeed.com/rc/clk?jk=99c10a7e4d2b3f01&from=ja">Junior Data Engineer</a><br>
<span>Quartzline Games</span><br><span>Las Vegas, NV</span><br></td></tr>
</table><a href="https://www.indeed.com/unsubscribe?x=1">Unsubscribe</a></body></html>"""

ZIP_HTML = """<html><body><h2>Jobs you may be interested in</h2>
<div><a href="https://www.ziprecruiter.com/k/l/AAJ1abc">Python Developer, Reporting Automation</a>
<div>Copperline Insurance</div><div>Remote (US)</div><div>$100K - $125K</div></div>
<div><a href="https://www.ziprecruiter.com/k/l/AAJ2def">Data Analyst II - Mortgage Default</a>
<div>Harbor Point Mortgage</div><div>Phoenix, AZ</div><div>$85,000 - $102,000/yr</div></div>
</body></html>"""

DESCRIPTIONS = {
    "Senior Data Analyst": """About the role: Join our servicing analytics team supporting default, bankruptcy and foreclosure operations.
You will build SQL reporting views, Tableau and Power BI dashboards and KPIs used by senior leadership.
Requirements: Bachelor's degree in Information Systems or related field. 4+ years of experience with SQL (T-SQL, Snowflake).
Experience with Python for automation. Familiarity with GitLab CI/CD and Jira. Strong stakeholder communication.
To apply, submit a resume and cover letter. Three professional references will be requested at the final stage.
This position requires a background check. Hybrid: 3 days in our Las Vegas office.""",
    "Analytics Engineer": """We're looking for an Analytics Engineer to own our dbt models in Snowflake and Airflow orchestration.
You'll partner with clinical ops on data modeling and data governance. Python and SQL required; experience with HL7 is a plus.
3+ years of experience in analytics engineering or data engineering. Fully remote within the US.
Cover letter optional. We are unable to sponsor visas for this role. Salary range $118,000 - $142,000 per year.""",
    "BI Developer": """Design and maintain Tableau and Power BI dashboards for member and lending analytics. Write SQL Server stored procedures
and SSIS packages. 2+ years of experience required. Excel and VBA skills a plus. On-site in Henderson, NV.
Please include a list of three references with your application. Drug screen and background check required.""",
    "Data Engineer - Healthcare": """Build HL7 v2 and FHIR ingestion pipelines into Snowflake using Python and PySpark. Model data in PostgreSQL,
deploy with Docker and GitHub Actions CI/CD on AWS. 3+ years of data engineering experience. Remote.
Applicants must be authorized to work in the US; we will not sponsor. Please share a GitHub profile or portfolio of related work.""",
    "Database Developer": """Mesa Verde County seeks a Database Developer to maintain T-SQL stored procedures, views and SSRS reports for county
departments. Bachelor's degree and 2 years of experience. Applicants must attach a cover letter, resume and transcripts.
Applicants may be asked to complete a skills assessment. Background investigation required. Closes in 3 weeks.""",
    "Junior Data Engineer": """Help build the data platform behind our skill-based gaming apps. Python, SQL, PostgreSQL, Supabase and REST APIs.
React Native experience is a bonus. 1+ years of experience. On-site in Las Vegas. Salary $78,000 - $92,000.""",
    "Python Developer": """Automate reporting workflows in Python and SQL. Work with REST APIs, Postman, Docker and Git. Agile team using Jira.
Remote US. Take-home coding exercise is part of the process. 3+ years of experience.""",
    "Data Analyst II": """Analyze mortgage default and loss-mitigation data. SQL, Excel, Tableau. Forecasting and variance analysis.
2+ years of experience in mortgage servicing. Cover letter required. Hybrid in Phoenix, AZ.""",
}
POSTED = {"Senior Data Analyst": 3, "Analytics Engineer": 1, "BI Developer": 6, "Data Engineer - Healthcare": 2,
          "Database Developer": 9, "Junior Data Engineer": 0, "Python Developer": 4, "Data Analyst II": 12}


def _email(frm, subject, html, days):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "you@example.com", subject
    m["Date"] = format_datetime(D(days))
    m["Message-ID"] = f"<demo-{abs(hash(subject))}@dispatch>"
    m.set_content("View this email in HTML.")
    m.add_alternative(html, subtype="html")
    return m.as_bytes()


def demo_jobs():
    out = []
    for raw in (_email("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "data analyst in Las Vegas: 3 new jobs", LINKEDIN_HTML, 0),
                _email("Indeed <alert@indeed.com>", '3 new jobs for "data engineer"', INDEED_HTML, 1),
                _email("ZipRecruiter <alerts@ziprecruiter.com>", "Jobs you may be interested in", ZIP_HTML, 2)):
        meta, jobs = parse_message(raw)
        meta["message_id"] = "demo-" + meta["message_id"]
        for j in jobs:
            for key, desc in DESCRIPTIONS.items():
                if j["title"].startswith(key):
                    j["description"] = desc
                    j["posted_date"] = D(POSTED[key]).date().isoformat()
            j["demo"] = 1
            j["enrich_status"] = "demo"
            j["seen_in"] = [meta["subject"]]
            analyze(j)
            out.append(j)
    return out
