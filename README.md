# Dispatch

Your job-search command center. It runs free on your own computer and has four sections:

- **Jobs**: postings from your email job alerts, each with pay, date posted, location, skills matched to your resume, what you need to submit (cover letter, references…), and an Apply button.
- **Applications**: everything you've applied to, tracked automatically. No spreadsheet needed. Employer emails add and update them (confirmations, rejections, interview invites, offers), and jobs you mark Applied in Dispatch land here too.
- **Insights**: charts of your progress. Applications per week, where you stand, a map of the cities you've applied to, top cities, area of focus, opened vs. closed, how long until you hear back, a daily activity calendar, and where you applied.
- **Radar**: Dispatch's own job hunt. Every few hours it searches job boards and the career sites of companies you've applied to, then sends you an email digest (it reaches your phone too) and a Windows notification about new roles that fit you.

## Opening it

1. **First time:** double-click **Start Dispatch.bat** in this folder. It sets itself up in about a minute (it needs Python 3; if that's missing, the window tells you where to get it free). It also adds a **Dispatch** icon to your desktop and Start menu.
2. **After that:** double-click the **Dispatch** icon. It opens in its own window, like an app.
3. Want Radar and email checks running all day without opening it? Settings → **Start with Windows**.

Dispatch is a private web app that lives on your computer at http://127.0.0.1:5057. No account or hosting is needed, and it costs nothing. Your data and passwords never leave your PC except to sign in to your own email.

## Connect your Gmail (one time)

The first time Dispatch opens, it shows **Connect your Gmail** with jordangillis74@gmail.com already filled in. Google requires you to approve any app that reads your mail, so:

1. Click **Open Google approval page** and sign in. If Google asks you to turn on 2-Step Verification, do that first.
2. Type "Dispatch" as the app name and click **Create**. Google shows a 16-letter code.
3. Paste the code into Dispatch and click **Connect and start reading**.

That's the only manual step. Dispatch then reads your job alerts and employer replies on its own, checking every hour. It only reads mail; it never deletes anything or marks it as read. To add another inbox, use Settings → Email accounts. To disconnect, delete the "Dispatch" entry on that same Google page.

## What happens automatically

- **New applications:** a "thank you for applying" email from an employer, LinkedIn, Indeed or a careers site adds the application. If it's a job Dispatch already found (from an alert or Radar), the application picks up that posting's pay, location, posted date and link, and the job moves to Applied.
- **Status updates:** the latest employer email wins. "Unfortunately… other candidates" means **Not selected**, "schedule an interview" means **Interviewing**, and "pleased to offer" means **Offer**.
- **No response:** an application with no reply after 45 days is closed as **No response**.
- **Follow-up reminders:** after 10 days with no reply, an application is flagged **Follow up**. Open it to copy a ready-to-send follow-up email, then click **I followed up**.
- **Already-applied jobs:** new alert postings you've already applied to are filed under Applied instead of New.
- **Weekly report:** every Sunday evening you get an email with what you sent, what employers said, follow-ups due and the top Radar finds.
- **Radar** searches for new roles every 6 hours and emails you the good ones.

All the timings are adjustable in Settings → Automation. If Dispatch guesses a status wrong, open the application and pick the right one; **Automatic** hands it back to Dispatch.

**Old spreadsheet:** Dispatch doesn't use `Jobs.xlsx`. If you want your past applications in the charts, click **Import old history** once (Applications tab or Settings). It's a one-time copy, and **Remove imported history** in Settings takes it back out. **Download as spreadsheet** exports everything Dispatch tracks whenever you need a file.

## Radar

Radar's suggested search comes from your history (top focus areas and cities), and you can edit it on the Radar tab. It searches:

- **Job boards:** Remotive, RemoteOK and The Muse out of the box. Add free keys in Settings for **Adzuna** (best for local roles with pay), **USAJOBS** and **Jooble**.
- **Company career sites:** every Workday, Greenhouse, Lever, Ashby and SmartRecruiters company you've applied to (23 from your sheet so far), plus any you add.

It skips roles you've already applied to, anything older than your cutoff, and anything below your resume-match minimum. New finds are emailed to you from your own Gmail and show up on the Radar tab.

## Good to know

- Indeed, Glassdoor and ZipRecruiter often block automated page reads. For their alerts, Dispatch keeps what was in the email and says so.
- The city map and city lookups use OpenStreetMap; cities are looked up once and remembered.
- `data/` holds your settings, `jobs.db` and logs. Delete it to start fresh. Settings → **Quit Dispatch** stops it.
