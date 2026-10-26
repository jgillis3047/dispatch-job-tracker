"""Dispatch's own alerts: an email digest (works on your phone) and Windows desktop notifications."""
import html
import platform
import smtplib
import subprocess
from email.message import EmailMessage

from . import store
from .extract import salary_label
from .mail_reader import smtp_host

STATUS_WORD = {"rejected": "Not selected", "interview": "Interview / next step", "offer": "Offer", "withdrawn": "Closed by employer",
               "pending": "Application received"}


def _job_card(j):
    pay = salary_label(j.get("salary_min"), j.get("salary_max"), j.get("salary_period") or "year", j.get("salary_text"))
    meta = " · ".join(x for x in (j.get("company"), j.get("location"), pay, j.get("posted_date") and f"posted {j['posted_date']}") if x)
    m = f"{j['match']}% resume match" if j.get("match") is not None else ""
    return f"""<tr><td style="padding:14px 18px;border-bottom:1px solid #2D3C5E">
      <div style="font:600 17px Arial,sans-serif;color:#E9EDF4">{html.escape(j.get('title') or '')}</div>
      <div style="font:14px Arial,sans-serif;color:#93A0BA;margin:3px 0 8px">{html.escape(meta)}</div>
      <div style="font:13px Arial,sans-serif;color:#4CCBA9;margin-bottom:10px">{html.escape(' · '.join(x for x in (m, j.get('board') and 'via ' + j['board']) if x))}</div>
      <a href="{html.escape(j.get('apply_url') or j.get('url') or '#')}" style="display:inline-block;background:#F5B841;color:#1B1606;font:700 14px Arial,sans-serif;padding:8px 14px;border-radius:7px;text-decoration:none">Apply</a>
    </td></tr>"""


def build_digest(jobs, changes):
    rows = "".join(_job_card(j) for j in jobs[:15])
    ch = "".join(f"""<tr><td style="padding:10px 18px;border-bottom:1px solid #2D3C5E;font:14px Arial,sans-serif;color:#E9EDF4">
        <b>{html.escape(STATUS_WORD.get(c['status'], c['status']))}</b> — {html.escape(c.get('title') or '')} at {html.escape(c.get('company') or '')}</td></tr>"""
                 for c in changes)
    parts = []
    if changes:
        parts.append(f'<tr><td style="padding:16px 18px 6px;font:700 20px Arial,sans-serif;color:#F5B841">Application updates</td></tr>{ch}')
    if jobs:
        parts.append(f'<tr><td style="padding:18px 18px 6px;font:700 20px Arial,sans-serif;color:#F5B841">{len(jobs)} new role{"s" if len(jobs) != 1 else ""} that fit you</td></tr>{rows}')
    more = f'<tr><td style="padding:14px 18px;font:13px Arial,sans-serif;color:#93A0BA">Plus {len(jobs) - 15} more in Dispatch → Radar.</td></tr>' if len(jobs) > 15 else ""
    return f"""<html><body style="margin:0;background:#111A2E"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#111A2E">
      <tr><td align="center" style="padding:20px 10px"><table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#16213A;border-radius:12px">
      <tr><td style="padding:18px 18px 0;font:700 26px Arial,sans-serif;color:#E9EDF4">Dispatch</td></tr>{''.join(parts)}{more}
      <tr><td style="padding:16px 18px;font:12px Arial,sans-serif;color:#6A789A">Sent by Dispatch on your computer. Change what Radar looks for in Dispatch → Radar.</td></tr>
      </table></td></tr></table></body></html>"""


def send_email(subject, html_body, text_body):
    cfg = store.load_settings()
    accts = store.connected(cfg)
    if not accts:
        return "no account"
    acct = accts[0]
    to = cfg.get("alert_email_to") or acct["email"]
    msg = EmailMessage()
    msg["From"] = f"Dispatch <{acct['email']}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    host = smtp_host(acct["email"], acct.get("imap_host") or None)
    pw = (acct.get("app_password") or "").replace(" ", "")
    try:
        if host == "smtp.office365.com":
            with smtplib.SMTP(host, 587, timeout=30) as s:
                s.starttls(); s.login(acct["email"], pw); s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, 465, timeout=30) as s:
                s.login(acct["email"], pw); s.send_message(msg)
        return "sent"
    except Exception as e:
        return f"failed: {type(e).__name__}: {e}"


def desktop(title, body):
    if platform.system() != "Windows":
        return "not windows"
    t = title.replace("'", "''")[:80]
    b = body.replace("'", "''")[:200]
    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$n = $x.GetElementsByTagName('text'); $n.Item(0).AppendChild($x.CreateTextNode('{t}')) > $null; $n.Item(1).AppendChild($x.CreateTextNode('{b}')) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), capture_output=True)
        return "shown"
    except Exception as e:
        return f"failed: {e}"


def alert(new_jobs, changes, force_email=False):
    """Send whatever is enabled. Returns a dict describing what went out."""
    cfg = store.load_settings()
    out = {}
    if not new_jobs and not changes:
        return out
    bits = []
    if new_jobs:
        bits.append(f"{len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''} that fit you")
    rej = sum(1 for c in changes if c["status"] == "rejected")
    pos = sum(1 for c in changes if c["status"] in ("interview", "offer"))
    if pos:
        bits.append(f"{pos} interview/offer update{'s' if pos != 1 else ''}")
    if rej:
        bits.append(f"{rej} not selected")
    headline = ", ".join(bits)
    if cfg.get("alert_desktop_on", True):
        top = new_jobs[0] if new_jobs else None
        out["desktop"] = desktop("Dispatch: " + headline, (f"{top['title']} at {top.get('company') or ''}" if top else
                                                            f"{changes[0].get('title')} at {changes[0].get('company')}"))
    if cfg.get("alert_email_on", True) or force_email:
        text = headline + "\n\n" + "\n".join(f"- {j['title']} at {j.get('company')} ({j.get('apply_url') or j.get('url')})" for j in new_jobs[:15])
        out["email"] = send_email(f"Dispatch: {headline}", build_digest(new_jobs, changes), text)
    store.set_state(last_alert=store.now(), last_alert_result=out, last_alert_headline=headline)
    return out


def weekly(summary, finds):
    """Sunday progress report."""
    s = summary
    tile = lambda n, label: (f'<td style="padding:10px 12px;background:#1C2843;border-radius:8px;text-align:center">'
                             f'<div style="font:700 26px Arial,sans-serif;color:#F5B841">{n}</div>'
                             f'<div style="font:12px Arial,sans-serif;color:#93A0BA">{label}</div></td>')
    tiles = "<td width='8'></td>".join([tile(s["sent"], "applied this week"), tile(s["replies"], "employer replies"),
                                        tile(s["interviews"], "interviews"), tile(s["response_rate"] + "%" if isinstance(s["response_rate"], str) else f"{s['response_rate']}%", "response rate overall")])
    ups = "".join(f'<tr><td style="padding:8px 18px;font:14px Arial,sans-serif;color:#E9EDF4;border-bottom:1px solid #2D3C5E">'
                  f'<b>{html.escape(STATUS_WORD.get(u["status"], u["status"]))}</b> — {html.escape(u.get("title") or "")} at {html.escape(u.get("company") or "")}</td></tr>'
                  for u in s["updates"])
    fus = "".join(f'<tr><td style="padding:8px 18px;font:14px Arial,sans-serif;color:#E9EDF4;border-bottom:1px solid #2D3C5E">'
                  f'{html.escape(a.get("title") or "")} at {html.escape(a.get("company") or "")}'
                  f'<span style="color:#93A0BA"> · applied {html.escape(a.get("applied_on") or "")}</span></td></tr>' for a in s["follow_ups"])
    section = lambda title, body: (f'<tr><td style="padding:18px 18px 6px;font:700 19px Arial,sans-serif;color:#F5B841">{title}</td></tr>{body}' if body else "")
    body = f"""<html><body style="margin:0;background:#111A2E"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#111A2E">
      <tr><td align="center" style="padding:20px 10px"><table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#16213A;border-radius:12px">
      <tr><td style="padding:18px 18px 4px;font:700 26px Arial,sans-serif;color:#E9EDF4">Your week in Dispatch</td></tr>
      <tr><td style="padding:10px 18px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{tiles}</tr></table></td></tr>
      {section("What employers said", ups)}
      {section("Time to follow up", fus)}
      {section("Top Radar finds you haven't applied to", "".join(_job_card(j) for j in finds))}
      <tr><td style="padding:16px 18px;font:12px Arial,sans-serif;color:#6A789A">{s['total']} applications tracked. Turn this report off in Dispatch → Settings → Automation.</td></tr>
      </table></td></tr></table></body></html>"""
    text = (f"This week: {s['sent']} applied, {s['replies']} employer replies, {s['interviews']} interviews, {s['rejections']} not selected. "
            f"Response rate {s['response_rate']}%. {len(s['follow_ups'])} applications are due for a follow-up.")
    return send_email(f"Dispatch weekly: {s['sent']} applied, {s['replies']} replies, {s['interviews']} interviews", body, text)
