#!/usr/bin/env python3
"""Build the public-records tracker page.

Reads requests.toml (and the request text files it points to) and writes
docs/index.html, which GitHub Pages serves. Needs Python 3.11 or newer:

    python3.13 build.py
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("build.py needs Python 3.11 or newer. Try: python3.13 build.py")

import html
import tomllib
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "docs" / "index.html"
PRIVATE_MARKER = "%% NOT PUBLISHED BELOW %%"

# status -> (label shown on the page, colour class)
STATUSES = {
    "drafted": ("Drafted, not yet filed", "neutral"),
    "filed": ("Filed, awaiting acknowledgment", "waiting"),
    "acknowledged": ("Acknowledged, awaiting records", "waiting"),
    "partial": ("Partly fulfilled", "good"),
    "fulfilled": ("Fulfilled", "good"),
    "denied": ("Denied", "bad"),
    "appealed": ("Under appeal", "waiting"),
}


def esc(text):
    return html.escape(str(text), quote=True)


def parse_date(value, where):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        sys.exit(f"{where}: '{value}' is not a date in YYYY-MM-DD form")


def fmt(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def add_business_days(start, n):
    """n business days after start. Weekends are skipped; public holidays are not."""
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def published_text(path):
    text = path.read_text(encoding="utf-8")
    return text.split(PRIVATE_MARKER)[0].strip()


def key_dates(req, today):
    """Rows of (label, value, is_overdue) for the facts panel."""
    rid = req["id"]
    rows = []
    filed = parse_date(req.get("filed"), f"{rid}: filed")
    promised = parse_date(req.get("promised"), f"{rid}: promised")
    denied = parse_date(req.get("denied"), f"{rid}: denied")
    status = req["status"]

    if not filed:
        rows.append(("Filed", "Not yet filed", False))
        return rows

    rows.append(("Filed", fmt(filed), False))
    if req.get("reference"):
        rows.append(("Reference", req["reference"], False))

    ack_due = add_business_days(filed, 5)
    late = status == "filed" and today > ack_due
    rows.append(("Acknowledgment due", fmt(ack_due) + (" (overdue)" if late else ""), late))

    if promised:
        late = status in ("filed", "acknowledged") and today > promised
        rows.append(("Agency's promised date", fmt(promised) + (" (overdue)" if late else ""), late))

    if denied:
        appeal_by = denied + timedelta(days=30)
        late = status == "denied" and today > appeal_by
        rows.append(("Appeal deadline", fmt(appeal_by) + (" (passed)" if late else ""), late))

    if status in ("filed", "acknowledged", "appealed"):
        waiting = (today - filed).days
        rows.append(("Waiting", f"{waiting} day{'s' if waiting != 1 else ''}", False))
    return rows


def render_request(req, today):
    rid = req["id"]
    status = req.get("status", "")
    if status not in STATUSES:
        sys.exit(f"{rid}: status '{status}' is not one of {', '.join(STATUSES)}")
    label, tone = STATUSES[status]

    facts = "".join(
        f'<div class="fact{" overdue" if late else ""}"><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>'
        for k, v, late in key_dates(req, today)
    )

    events = sorted(
        req.get("event", []),
        key=lambda e: parse_date(e["date"], f"{rid}: event date"),
        reverse=True,
    )
    timeline = "".join(
        f'<li><time datetime="{esc(e["date"])}">{esc(fmt(parse_date(e["date"], rid)))}</time>'
        f"<span>{esc(e['note'])}</span></li>"
        for e in events
    ) or "<li><span>No activity yet.</span></li>"

    docs = req.get("document", [])
    if docs:
        doc_items = "".join(
            f'<li><a href="{esc(d["url"])}">{esc(d["title"])}</a>'
            + (f' <span class="muted">received {esc(fmt(parse_date(d["date"], rid)))}</span>' if d.get("date") else "")
            + "</li>"
            for d in docs
        )
        documents = f'<h3>Records received</h3><ul class="docs">{doc_items}</ul>'
    else:
        documents = '<h3>Records received</h3><p class="muted">None yet.</p>'

    text = published_text((HERE / req["text_file"]).resolve())

    return f"""
    <article class="request" id="{esc(rid)}">
      <header>
        <p class="agency">{esc(req['agency'])}</p>
        <h2>{esc(req['subject'])}</h2>
        <p class="badge {tone}">{esc(label)}</p>
      </header>
      <dl class="facts">{facts}</dl>
      <h3>Timeline</h3>
      <ol class="timeline">{timeline}</ol>
      {documents}
      <details>
        <summary>Read the request</summary>
        <div class="letter">{esc(text)}</div>
      </details>
    </article>"""


def render_why(why):
    """The 'why these requests' section: paragraphs, small data tables, a source link."""
    if not why:
        return ""
    parts = [f"<h2>{esc(why['heading'])}</h2>"]
    for para in why.get("before", []):
        parts.append(f"<p>{esc(para)}</p>")
    for table in why.get("table", []):
        head = "".join(f"<th>{esc(c)}</th>" for c in table["columns"])
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
            for row in table["rows"]
        )
        parts.append(
            f'<figure><figcaption>{esc(table["caption"])}</figcaption>'
            f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></figure>'
        )
    for para in why.get("after", []):
        parts.append(f"<p>{esc(para)}</p>")
    if why.get("source_url"):
        parts.append(
            f'<p class="muted">Source: <a href="{esc(why["source_url"])}">{esc(why["source_label"])}</a></p>'
        )
    return f'<section class="why">{"".join(parts)}</section>'


CSS = """
:root {
  --paper: #faf7f0; --card: #ffffff; --ink: #1f2420; --muted: #636b63;
  --rule: #ddd8cb; --accent: #2f5d50;
  --neutral-bg: #ebe8df; --neutral-fg: #4c524c;
  --waiting-bg: #fbefcf; --waiting-fg: #6f5200;
  --good-bg: #dcefdf; --good-fg: #1d5a2c;
  --bad-bg: #f8dedb; --bad-fg: #8c2318;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #171a18; --card: #1f2421; --ink: #e9e6dc; --muted: #a0a79f;
    --rule: #353b36; --accent: #8fc7b3;
    --neutral-bg: #303631; --neutral-fg: #c6ccc4;
    --waiting-bg: #4a3c10; --waiting-fg: #f3d98a;
    --good-bg: #1f4229; --good-fg: #a9dfb6;
    --bad-bg: #522019; --bad-fg: #f5b3aa;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 18px/1.6 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}
main { max-width: 44rem; margin: 0 auto; padding: 3rem 1rem 4rem; }
h1 { font-size: 2.1rem; line-height: 1.2; margin: 0 0 .5rem; text-wrap: balance; }
h2 { font-size: 1.3rem; line-height: 1.3; margin: .2rem 0 .7rem; text-wrap: balance; }
h3 {
  font: 600 .78rem/1.2 system-ui, sans-serif; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); margin: 1.6rem 0 .5rem;
}
a { color: var(--accent); }
.tagline { font-size: 1.15rem; color: var(--muted); margin: 0 0 1.5rem; }
.intro { margin: 0 0 1rem; }
.summary {
  display: grid; grid-template-columns: repeat(4, auto); justify-content: start;
  gap: .8rem 2.2rem; margin: 1.5rem 0 2.5rem;
  padding: 1rem 0; border-block: 1px solid var(--rule);
}
.summary div { font: 500 .9rem system-ui, sans-serif; color: var(--muted); }
.summary strong { display: block; font: 600 1.6rem/1.2 system-ui, sans-serif; color: var(--ink); }
.request {
  background: var(--card); border: 1px solid var(--rule); border-radius: 6px;
  padding: 1.5rem; margin: 0 0 1.5rem;
}
.agency { font: 600 .85rem system-ui, sans-serif; color: var(--accent); margin: 0; }
.badge {
  display: inline-block; font: 600 .8rem system-ui, sans-serif;
  padding: .25rem .7rem; border-radius: 99px; margin: 0;
}
.badge.neutral { background: var(--neutral-bg); color: var(--neutral-fg); }
.badge.waiting { background: var(--waiting-bg); color: var(--waiting-fg); }
.badge.good { background: var(--good-bg); color: var(--good-fg); }
.badge.bad { background: var(--bad-bg); color: var(--bad-fg); }
.facts { display: flex; flex-wrap: wrap; gap: .8rem 2rem; margin: 1.2rem 0 0; }
.fact dt { font: 500 .78rem system-ui, sans-serif; color: var(--muted); }
.fact dd { margin: 0; font: 500 1rem system-ui, sans-serif; }
.fact.overdue dd { color: var(--bad-fg); }
.timeline, .docs { list-style: none; margin: 0; padding: 0; }
.timeline li { display: grid; grid-template-columns: 10.5rem 1fr; gap: 1rem; padding: .3rem 0; }
.timeline time { font: 500 .88rem/1.9 system-ui, sans-serif; color: var(--muted); }
.docs li { padding: .2rem 0; }
.muted { color: var(--muted); font-size: .95rem; margin: 0; }
details { margin-top: 1.6rem; border-top: 1px solid var(--rule); padding-top: 1rem; }
summary { cursor: pointer; font: 600 .9rem system-ui, sans-serif; color: var(--accent); }
.letter { white-space: pre-wrap; font-size: .95rem; margin-top: 1rem; overflow-wrap: anywhere; }
.why { margin: 2.5rem 0 0; }
.why h2 { font-size: 1.5rem; }
figure { margin: 1.4rem 0; }
figcaption { font: 600 .9rem system-ui, sans-serif; margin-bottom: .4rem; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font: .92rem system-ui, sans-serif; }
th, td { text-align: right; padding: .4rem .7rem; border-bottom: 1px solid var(--rule); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { font-weight: 600; color: var(--muted); }
td { font-variant-numeric: tabular-nums; }
footer { margin-top: 3rem; font: .85rem/1.5 system-ui, sans-serif; color: var(--muted); }
footer p { margin: 0 0 .5rem; }
@media (max-width: 520px) {
  body { font-size: 17px; }
  h1 { font-size: 1.7rem; }
  .request { padding: 1.1rem; }
  .summary { grid-template-columns: repeat(2, 1fr); }
  .timeline li { grid-template-columns: 1fr; gap: 0; }
}
"""


def main():
    data = tomllib.loads((HERE / "requests.toml").read_text(encoding="utf-8"))
    site = data["site"]
    requests = data.get("request", [])
    today = date.today()

    filed = sum(1 for r in requests if r.get("filed"))
    waiting = sum(1 for r in requests if r.get("status") in ("filed", "acknowledged", "appealed"))
    received = sum(len(r.get("document", [])) for r in requests)
    intro = " ".join(site["intro"].split())

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(site['title'])}</title>
<meta name="description" content="{esc(site['tagline'])}">
<style>{CSS}</style>
</head>
<body>
<main>
  <h1>{esc(site['title'])}</h1>
  <p class="tagline">{esc(site['tagline'])}</p>
  <p class="intro">{esc(intro)}</p>
  {render_why(data.get("why"))}
  <div class="summary">
    <div><strong>{len(requests)}</strong>requests</div>
    <div><strong>{filed}</strong>filed</div>
    <div><strong>{waiting}</strong>awaiting a response</div>
    <div><strong>{received}</strong>records received</div>
  </div>
  {''.join(render_request(r, today) for r in requests)}
  <footer>
    <p>Last updated {esc(fmt(today))}.</p>
    <p>Under New York's Freedom of Information Law an agency must acknowledge a request
    within five business days, and a denial can be appealed within 30 days. Deadlines shown
    here skip weekends but not public holidays.</p>
  </footer>
</main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(HERE)} ({len(requests)} requests)")


if __name__ == "__main__":
    main()
