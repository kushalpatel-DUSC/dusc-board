#!/usr/bin/env python3
"""Turn the rows of the DUSC Club Calendar sheet into the calendar data files.

Usage
  python3 scripts/build_calendar.py rows.json --board         (in the dusc-board repo)
      writes data/calendar.json and updates meta.json -> "calendar"
  python3 scripts/build_calendar.py rows.json --site .        (in the dusc-calendar repo)
      writes data/calendar.json, data/families.json, calendar.ics, families.ics, version.json

rows.json is a JSON list with one object per EVENT row of the sheet (skip the section title rows
and the header rows):
  {"section":  "General" | "Academy" | "Rec League" | "Classes" | "Camps" | "Major Events",
   "dateText": the Date / Date(s) cell exactly as shown, e.g. "Mon-Thu, Dec 28-31" or "TBD",
   "group":    the Group cell ("" in the General section),
   "event":    the Event cell,
   "people":   the People Involved cell,
   "status":   the Status cell ("Draft", "Set by league", ...),
   "notes":    the Notes cell,
   "start":    the Start date cell as YYYY-MM-DD, or "" when the date is not set,
   "end":      the End date cell as YYYY-MM-DD ("" = same as start),
   "owner":    the Owner cell,
   "families": true when the "Show to families" cell says Yes,
   "dates":    OPTIONAL list of YYYY-MM-DD, only when the row names separate days rather than a span
               (e.g. "Nov 5, 12, 20" or "Sat, Nov 21 / Sun, Nov 22 / Sun, Dec 6")}

When a row has a date in the Date cell but an empty Start date cell, work the date out yourself and
put it in "start"/"end": the season runs Aug 1 2026 to Jul 31 2027, so Aug-Dec is 2026 and Jan-Jul is
2027 (summer camp weeks in August are August 2027).
The script checks every date, drops nothing silently, and prints what it did.
"""
import datetime, hashlib, json, os, re, sys

SECTIONS = ['General', 'Academy', 'Rec League', 'Classes', 'Camps', 'Major Events']
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1gw2G8kcw1Umd4Cm1jRoVbY8yHm4k5sKgXb5iw8xGHzA/edit'


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
    with open(sys.argv[1], encoding='utf-8') as f:
        rows = json.load(f)
    if not isinstance(rows, list) or len(rows) < 20:
        print('rows.json must be a JSON list of the sheet\'s event rows (found %s) - nothing written' % (len(rows) if isinstance(rows, list) else type(rows).__name__)); sys.exit(2)
    events, problems = build(rows)
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
        write_json(os.path.join(out, 'data', 'calendar.json'), {'meta': meta, 'events': events})
        write_json(os.path.join(out, 'data', 'families.json'), {'meta': {'updatedAt': now, 'total': len(fam)}, 'events': [family_view(e) for e in fam]})
        with open(os.path.join(out, 'calendar.ics'), 'w', encoding='utf-8', newline='') as f:
            f.write(ics(dated, 'DUSC Club Calendar (staff)', False))
        with open(os.path.join(out, 'families.ics'), 'w', encoding='utf-8', newline='') as f:
            f.write(ics(fam, 'DUSC Club Calendar', True))
        body = json.dumps([events, [family_view(e) for e in fam]], sort_keys=True, ensure_ascii=False).encode('utf-8')
        write_json(os.path.join(out, 'data', 'version.json'), {'v': hashlib.sha1(body).hexdigest()[:10], 'updatedAt': now})
    print('build_calendar: %d events, %d dated, %d to be set, %d shown to families%s' % (len(events), len(dated), len(events) - len(dated), len(fam), ('; ' + '; '.join(problems[:6])) if problems else ''))


if __name__ == '__main__':
    main()
