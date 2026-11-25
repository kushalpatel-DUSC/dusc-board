#!/usr/bin/env python3
"""Turn the DUSC Club Calendar sheet into the calendar data files.

Usage
  python3 scripts/build_calendar.py <sheet.csv> --board        (in the dusc-board repo)
      writes data/calendar.json and updates meta.json -> "calendar"
  python3 scripts/build_calendar.py <sheet.csv> --site .       (in the dusc-calendar repo)
      writes data/calendar.json, data/families.json, data/version.json, calendar.ics, families.ics

<sheet.csv> is the sheet exported as CSV, exactly as Google Drive gives it: download the file with the
Drive connector's download tool (exportMimeType "text/csv"); the tool saves the CSV and returns its path.
Do not retype or summarise the sheet: pass the downloaded file.

The sheet is one tab with six stacked sections. The first ("General") uses the columns
Date, Day, Event, People Involved, Notes. Then "Academy", "Rec League", "Classes", "Camps" and
"Major Events" each start with a title row and a header row and use
Date(s), Group, Event, (blank), People Involved, Status, Notes. Every section also has four columns on the
right: Start date, End date, Owner, Show to families.
A row with a date in its Date cell but no Start date is still read: the date is worked out from the text
(the season runs Aug 1 2026 to Jul 31 2027, so Aug-Dec is 2026 and Jan-Jul is 2027; summer camp weeks in
August are August 2027) and the row is listed under "problems" so someone can fill in Start date.
(A .json file of row objects is also accepted, for tests.)
The script checks every date, drops nothing silently, and prints what it did.
"""
import csv, datetime, hashlib, json, os, re, sys

SECTIONS = ['General', 'Academy', 'Rec League', 'Classes', 'Camps', 'Major Events']
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1gw2G8kcw1Umd4Cm1jRoVbY8yHm4k5sKgXb5iw8xGHzA/edit'


MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}


def cell_date(v):
    """A Start/End date cell -> YYYY-MM-DD, '' when empty, None when it cannot be read."""
    v = str(v or '').strip()
    if not v:
        return ''
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', v)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', v)
        if m:
            mo, d, y = map(int, m.groups()); y += 2000 if y < 100 else 0
        else:
            m = re.match(r'^(?:[A-Za-z]{3,9},?\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$', v)
            if not m or m.group(1)[:3].lower() not in MON:
                return None
            mo, d, y = MON[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return None


def text_dates(text, section, event):
    """Every date named in a Date cell, in order; a bare day number takes the month before it."""
    t = str(text or '').replace('\n', '; ')
    if not t.strip() or re.search(r'tbd|end of', t, re.I):
        return []
    out, cur = [], None
    for m in re.finditer(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)[a-z]*\.?|(\d{4})|(\d{1,2})', t):
        if m.group(1):
            cur = MON[m.group(1)[:3].lower()]
        elif m.group(2):
            if out:
                out[-1] = (int(m.group(2)),) + out[-1][1:]
        elif cur:
            yr = 2027 if (section == 'Camps' and cur in (8, 9) and 'summer' in str(event).lower()) else (2026 if cur >= 8 else 2027)
            out.append((yr, cur, int(m.group(3))))
    res = []
    for d in out:
        try:
            res.append(datetime.date(*d).isoformat())
        except ValueError:
            pass
    return res


def rows_from_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        table = [r + [''] * (11 - len(r)) for r in csv.reader(f)]
    rows, notes, section = [], [], 'General'
    for r in table:
        first = r[0].strip()
        if first in SECTIONS and not any(x.strip() for x in r[1:]):
            section = first; continue
        if first.startswith('Date') or not any(x.strip() for x in r[:7]):
            continue
        if section == 'General':
            o = dict(dateText=r[0], group='', event=r[2], people=r[3], status='', notes=r[4])
        else:
            o = dict(dateText=r[0], group=r[1], event=r[2], people=r[4] or r[3], status=r[5], notes=r[6])
        if not o['event'].strip():
            continue
        start, end = cell_date(r[7]), cell_date(r[8])
        named = text_dates(o['dateText'], section, o['event'])
        if start is None or end is None:
            notes.append('"%s": Start/End date cell could not be read (%r, %r); used the Date text instead' % (o['event'][:50], r[7], r[8])); start, end = '', ''
        if not start and named:
            start, end = named[0], named[-1]
            notes.append('"%s" (%s): no Start date in the sheet; read %s from the Date text' % (o['event'][:50], section, start))
        o.update(section=section, start=start, end=end or start, owner=r[9], families=r[10].strip().lower() in ('yes', 'y', 'true', 'x'))
        # separate days rather than one span: several dates in the cell and no dash joining them
        if len(named) > 1 and not re.search(r'[–—-]', o['dateText']) and start == named[0] and (end or start) == named[-1]:
            o['dates'] = named
        rows.append(o)
    return rows, notes


def iso(v):
    v = str(v or '').strip()
    if not v:
        return ''
    try:
        return datetime.date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        return None


def slug(*parts):
    s = '-'.join(str(p or '') for p in parts).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:70] or 'event'


def build(rows):
    events, problems, seen = [], [], {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or not str(r.get('event') or '').strip():
            problems.append('row %d has no event text: skipped' % (i + 1)); continue
        section = str(r.get('section') or 'General').strip()
        if section not in SECTIONS:
            problems.append('row %d: unknown section %r, filed under General' % (i + 1, section)); section = 'General'
        start, end = iso(r.get('start')), iso(r.get('end'))
        if start is None or end is None:
            problems.append('row %d (%s): unreadable date, treated as not set' % (i + 1, r.get('event'))); start, end = '', ''
        if start and not end:
            end = start
        if start and end < start:
            problems.append('row %d (%s): end before start, end ignored' % (i + 1, r.get('event'))); end = start
        dates = [d for d in (iso(x) for x in (r.get('dates') or [])) if d]
        if dates:
            dates = sorted(set(dates)); start, end = start or dates[0], end or dates[-1]
        status = str(r.get('status') or '').strip()
        ev = {
            'section': section,
            'group': str(r.get('group') or '').strip(),
            'title': ' '.join(str(r.get('event')).split()),
            'dateText': ' / '.join(x.strip() for x in str(r.get('dateText') or '').splitlines() if x.strip()),
            'start': start or None, 'end': end or None,
            'tbd': not start,
            'people': str(r.get('people') or '').strip(),
            'owner': str(r.get('owner') or '').strip(),
            'status': status,
            'draft': 'draft' in status.lower(),
            'notes': ' '.join(str(r.get('notes') or '').split()),
            'families': bool(r.get('families')) and str(r.get('families')).strip().lower() not in ('no', 'false', '0', ''),
            'order': i,
        }
        if len(dates) > 1:
            ev['dates'] = dates
        base = slug(section, ev['group'], ev['title'])
        n = seen.get(base, 0); seen[base] = n + 1
        ev['id'] = base if n == 0 else '%s-%d' % (base, n + 1)
        events.append(ev)
    return events, problems


def family_view(ev):
    """What a family may see: confirmed, dated, marked for families. No people, owners, status or notes."""
    out = {k: ev[k] for k in ('id', 'section', 'group', 'title', 'start', 'end')}
    if ev.get('dates'):
        out['dates'] = ev['dates']
    return out


def ics(events, name, family):
    def esc(t):
        return str(t or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')

    def fold(line):
        b = line.encode('utf-8'); out = []
        while len(b) > 73:
            cut = 73
            while cut > 0 and (b[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(b[:cut].decode('utf-8')); b = b' ' + b[cut:]
        out.append(b.decode('utf-8'))
        return '\r\n'.join(out)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//DUSC//Club Calendar//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
         'X-WR-CALNAME:' + esc(name), 'X-WR-TIMEZONE:America/New_York', 'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H']
    for ev in events:
        if not ev.get('start'):
            continue
        spans = [(d, d) for d in ev['dates']] if ev.get('dates') else [(ev['start'], ev['end'] or ev['start'])]
        for k, (s, e) in enumerate(spans):
            d1 = datetime.date.fromisoformat(s); d2 = datetime.date.fromisoformat(e) + datetime.timedelta(days=1)
            title = ev['title'] if not ev.get('group') or ev['group'].lower() in ev['title'].lower() else '%s: %s' % (ev['group'], ev['title'])
            desc = [ev['section']]
            if not family:
                if ev.get('status'): desc.append('Status: ' + ev['status'])
                if ev.get('owner'): desc.append('Owner: ' + ev['owner'])
                if ev.get('people'): desc.append('People: ' + ev['people'])
                if ev.get('notes'): desc.append(ev['notes'])
            L += ['BEGIN:VEVENT', 'UID:%s-%d@dusc-club-calendar' % (ev['id'], k), 'DTSTAMP:' + stamp,
                  'DTSTART;VALUE=DATE:' + d1.strftime('%Y%m%d'), 'DTEND;VALUE=DATE:' + d2.strftime('%Y%m%d'),
                  'SUMMARY:' + esc(title), 'DESCRIPTION:' + esc('\n'.join(desc)), 'CATEGORIES:' + esc(ev['section']), 'TRANSP:TRANSPARENT', 'END:VEVENT']
    L.append('END:VCALENDAR')
    return '\r\n'.join(fold(x) for x in L) + '\r\n'


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True); f.write('\n')


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in ('--board', '--site'):
        print(__doc__); sys.exit(2)
    src, notes = sys.argv[1], []
    if src.lower().endswith('.json'):
        with open(src, encoding='utf-8') as f:
            rows = json.load(f)
    else:
        rows, notes = rows_from_csv(src)
    if not isinstance(rows, list) or len(rows) < 100:
        print('Only %s event rows were read from %s (the sheet has about 160). Nothing written - check that the whole sheet was downloaded as CSV.' % (len(rows) if isinstance(rows, list) else 0, src)); sys.exit(2)
    events, problems = build(rows)
    problems = notes + problems
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    dated = [e for e in events if not e['tbd']]
    fam = [e for e in dated if e['families'] and not e['draft']]
    meta = {'updatedAt': now, 'sheetUrl': SHEET_URL, 'total': len(events), 'dated': len(dated), 'tbd': len(events) - len(dated), 'families': len(fam), 'problems': problems[:20]}
    if sys.argv[2] == '--board':
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        write_json(os.path.join(root, 'calendar.json'), {e['id']: e for e in events})
        mp = os.path.join(root, 'meta.json')
        with open(mp, encoding='utf-8') as f:
            m = json.load(f)
        m['calendar'] = meta
        write_json(mp, m)
    else:
        out = sys.argv[3] if len(sys.argv) > 3 else '.'
        body = json.dumps([events, [family_view(e) for e in fam]], sort_keys=True, ensure_ascii=False).encode('utf-8')
        ver = hashlib.sha1(body).hexdigest()[:10]
        try:
            with open(os.path.join(out, 'data', 'version.json'), encoding='utf-8') as f:
                if json.load(f).get('v') == ver and os.path.exists(os.path.join(out, 'data', 'calendar.json')):
                    print('build_calendar: no change since the last build (%d events, %d shown to families)%s' % (len(events), len(fam), ('; ' + '; '.join(problems[:6])) if problems else '')); return
        except (OSError, ValueError):
            pass
        write_json(os.path.join(out, 'data', 'calendar.json'), {'meta': meta, 'events': events})
        write_json(os.path.join(out, 'data', 'families.json'), {'meta': {'updatedAt': now, 'total': len(fam)}, 'events': [family_view(e) for e in fam]})
        with open(os.path.join(out, 'calendar.ics'), 'w', encoding='utf-8', newline='') as f:
            f.write(ics(dated, 'DUSC Club Calendar (staff)', False))
        with open(os.path.join(out, 'families.ics'), 'w', encoding='utf-8', newline='') as f:
            f.write(ics(fam, 'DUSC Club Calendar', True))
        write_json(os.path.join(out, 'data', 'version.json'), {'v': ver, 'updatedAt': now})
    print('build_calendar: %d events, %d dated, %d to be set, %d shown to families%s' % (len(events), len(dated), len(events) - len(dated), len(fam), ('; ' + '; '.join(problems[:6])) if problems else ''))


if __name__ == '__main__':
    main()
