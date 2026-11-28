#!/usr/bin/env python3
"""List what each of KP's new cards might be connected to. Read-only: prints JSON, writes nothing.

Usage:  python3 scripts/connect_candidates.py [--max 20]

For every open card whose "connect" is {"state": "pending"} (the board sets that on cards KP adds from
his quick list) it prints the card and its nearest neighbours among the board's own records:
  notes   meeting notes, with the exact lines that matched (a to-do, a decision, a key point)
  emails  threads recorded on the old Reply list in the last 30 days (retired 2026-11-27, so this runs dry)
  cards   his other open cards, as possible duplicates
and the list of project names. It also prints KP's categories and his open cards that have no category yet
("uncategorised"). Neighbours are found by shared words only, so most are wrong: whether
one really is about the same piece of work is for the reader to judge.
"""
import datetime, json, math, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
STOP = set("""a an and are as at be been but by can could did do does for from get got had has have he her him his how i if in into is it its
just let me my need needs new not now of on once one or our out over she should so some than that the their them then there these they this
to too up us was we were what when where which who why will with would you your about after again all also any back before both each
make made more most much must next other per same see send sent set still such take talk tell them thing things think through until
very via want week weeks day days today tomorrow yesterday call email ask check follow look update updates meeting notes note kp kushal
re fw fwd dusc club team""".split())
OPEN = ('todo', 'doing', 'waiting')


def load(name):
    p = os.path.join(ROOT, name + '.json')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        txt = f.read().strip()
    return json.loads(txt) if txt else {}


def toks(text):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9'&./-]*", str(text or '').lower()):
        w = w.strip("'./-")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 4 and w.endswith('ies'):
            w = w[:-3] + 'y'
        elif len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
            w = w[:-1]
        if len(w) < 3 and not w.isdigit():
            continue
        if w in STOP:
            continue
        out.append(w)
    return out


def clean_url(u):
    u = str(u or '')
    u = re.sub(r'([?&])authuser=[^&#]*&?', r'\1', u)
    return u.replace('?#', '#').replace('&#', '#').rstrip('?&')


def main():
    mx = 20
    if '--max' in sys.argv:
        mx = int(sys.argv[sys.argv.index('--max') + 1])
    cards, notes, inbox, meta = load('cards'), load('notes'), load('inbox'), load('meta')
    today = datetime.date.today()

    def recent(d, days):
        try:
            return (today - datetime.date.fromisoformat(str(d)[:10])).days <= days
        except Exception:
            return False

    pending = [(cid, c) for cid, c in cards.items()
               if isinstance(c.get('connect'), dict) and c['connect'].get('state') == 'pending' and c.get('status') in OPEN]
    pending.sort(key=lambda kv: str(kv[1]['connect'].get('askedAt') or kv[1].get('createdAt') or ''))

    # every line a card could match, with where it came from
    note_lines = {}
    for nid, n in notes.items():
        lines = [('title', n.get('title'))]
        lines += [('summary', s) for s in re.split(r'(?<=[.!?])\s+', str(n.get('summary') or '')) if s.strip()]
        lines += [('key point', x) for x in (n.get('keyPoints') or [])]
        lines += [('decision', x) for x in (n.get('decisions') or [])]
        lines += [('open question', x) for x in (n.get('openQuestions') or [])]
        for a in (n.get('actions') or []):
            if isinstance(a, dict) and a.get('text'):
                lines.append(('to-do' + (' for ' + a['owner'] if a.get('owner') and a['owner'] != 'TBD' else ''), a['text']))
        note_lines[nid] = [(k, str(t)) for k, t in lines if t]
    mail_text = {mid: ' '.join(str(m.get(k) or '') for k in ('subject', 'from', 'gist', 'ask')) for mid, m in inbox.items()
                 if recent(m.get('date'), 30)}   # the Reply list was retired on 2026-11-27; what is left of it fades out
    other_cards = {cid: c for cid, c in cards.items() if c.get('status') in OPEN}

    # rarer words count for more
    docs = [set(toks(t)) for ls in note_lines.values() for _, t in ls] + [set(toks(t)) for t in mail_text.values()] + [set(toks(c.get('title'))) for c in other_cards.values()]
    df = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    N = max(1, len(docs))
    idf = lambda w: math.log(1 + N / (1 + df.get(w, 0)))

    def score(q, text):
        t = set(toks(text))
        hit = q & t
        return sum(idf(w) for w in hit), sorted(hit)

    out = []
    for cid, c in pending[:mx]:
        q = set(toks(c.get('title')) + toks(c.get('note')))
        total = sum(idf(w) for w in q) or 1.0
        res = {'card': {'id': cid, 'title': c.get('title'), 'due': c.get('due'), 'project': c.get('project'), 'note': c.get('note'), 'raised': c.get('raised'),
                        'askedAt': c['connect'].get('askedAt'), 'listId': c['connect'].get('listId')},
               'notes': [], 'emails': [], 'cards': []}
        ns = []
        for nid, lines in note_lines.items():
            scored = sorted(((score(q, t), k, t) for k, t in lines), key=lambda x: -x[0][0])
            best = scored[0][0][0] if scored else 0
            if best <= 0:
                continue
            n = notes[nid]
            words = sorted({w for (s, hit), _, _ in scored for w in hit})
            s = best + 0.25 * sum(idf(w) for w in words)
            if recent(n.get('date'), 30):
                s *= 1.2
            if len(words) < 2 and best / total < 0.5:
                continue
            ns.append((s, {'kind': 'note', 'ref': nid, 'title': n.get('title'), 'date': n.get('date'), 'url': clean_url(n.get('url')), 'shared': words,
                           'lines': [{'what': k, 'text': t[:260]} for (sc, hit), k, t in scored[:3] if sc > 0]}))
        res['notes'] = [x for _, x in sorted(ns, key=lambda x: -x[0])[:4]]
        ms = []
        for mid, text in mail_text.items():
            s, hit = score(q, text)
            if s <= 0 or (len(hit) < 2 and s / total < 0.5):
                continue
            m = inbox[mid]
            if recent(m.get('date'), 21):
                s *= 1.2
            ms.append((s, {'kind': 'email', 'ref': mid, 'threadId': m.get('threadId') or mid, 'subject': m.get('subject'), 'from': m.get('from'), 'date': str(m.get('date') or '')[:10],
                           'status': m.get('status'), 'url': clean_url(m.get('threadUrl')), 'ask': m.get('ask'), 'gist': str(m.get('gist') or '')[:260], 'due': m.get('due'), 'shared': hit}))
        res['emails'] = [x for _, x in sorted(ms, key=lambda x: -x[0])[:4]]
        cs = []
        for oid, o in other_cards.items():
            if oid == cid:
                continue
            s, hit = score(q, o.get('title'))
            if s / total < 0.5 or len(hit) < 2:
                continue
            cs.append((s, {'kind': 'card', 'ref': oid, 'title': o.get('title'), 'status': o.get('status'), 'due': o.get('due'), 'project': o.get('project'),
                           'source': o.get('source'), 'pendingToo': isinstance(o.get('connect'), dict) and o['connect'].get('state') == 'pending', 'shared': hit}))
        res['cards'] = [x for _, x in sorted(cs, key=lambda x: -x[0])[:3]]
        out.append(res)

    # KP's open cards that have no "cats" field at all (the board could not place them); an empty list is his own choice and is left alone
    uncat = [{'id': cid, 'title': c.get('title'), 'note': c.get('note'), 'project': c.get('project'), 'source': c.get('source')}
             for cid, c in cards.items() if isinstance(c, dict) and c.get('status') in OPEN and (c.get('owner') or 'KP') == 'KP' and c.get('cats') is None]
    print(json.dumps({'today': today.isoformat(), 'projects': [p.get('name') for p in ((meta.get('projects') or {}).get('items') or []) if p.get('name')],
                      'categories': [{'id': k.get('id'), 'name': k.get('name')} for k in ((meta.get('categories') or {}).get('items') or []) if isinstance(k, dict)],
                      'pending': out, 'waiting': max(0, len(pending) - mx), 'uncategorised': uncat[:20]}, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
