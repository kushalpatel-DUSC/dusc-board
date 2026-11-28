#!/usr/bin/env python3
"""Apply a list of operations to the board's data files.

Usage:  python3 scripts/apply_ops.py ops.json
ops.json = [ {"coll": "cards", "id": "mlk-tuesday-space", "op": "merge", "patch": {...}, "source": "sync"}, ... ]

op: "set" (replace the whole doc), "merge" (shallow-merge fields), "delete", and
"agenda_done" (meetings only; patch {"texts": [...]} marks the agenda items with those exact texts as
done and changes nothing else - safe on agendas the user has edited).
source "sync" (the scheduled tasks) is guarded: it never deletes, never writes the inbox collection at all (the
Reply list was retired on 2026-11-27), and never overrides fields the user has edited (userEdited: true) on cards,
meetings or series. On notes it can add to the "actions" list (other people's to-dos) or mark one
done, but never removes or unticks one, and it keeps the user's keep/archive marks on to-dos and open
questions. A card the user dismissed or archived is never re-created. On a meeting it can record the
day-before agenda work ("prework") once and the after-meeting recap ("recap") once, never again, and it never touches "preworkDone" (the user's
mark that the agenda email is dealt with); on a series it never touches "notesDoc" (the running notes doc
the user linked). On a card it can write "connect" (what the card was tied to: notes, emails, a suggested
date or project) only while the card's connect.state is "pending", so each card is connected once and a
link the user removed never comes back. A time the user put on a card ("time", "mins") is the user's:
the sync proposes times only in meta/dayplan, which the page shows under "Plan my day". The category list
(meta/categories) is the user's too: a sync never writes it, may give a card its first "cats" (valid ids, two at
most) and never changes "cats" on a card that already has the field; projects keep their "cat". The page (source "user") has no guard.
The club calendar (data/calendar.json) is written by scripts/build_calendar.py, not by this script.
Prints a one-line summary. Exit code 0 on success.
"""
import json, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
COLLS = ['cards', 'notes', 'inbox', 'meetings', 'series', 'meta']
PROTECTED = {
    'cards': {'status', 'title', 'owner', 'due', 'note', 'priority', 'pinned', 'pinnedAt', 'waitingOn', 'waitingSince', 'doneAt', 'area', 'userEdited', 'triage', 'dismissedAt', 'snoozes', 'project', 'later', 'laterAt', 'keptAt', 'archivedAt', 'time', 'mins'},
    'meetings': {'agenda', 'agendaUpdatedAt', 'agendaSentAt', 'userEdited', 'skipAgenda', 'agendaSkip', 'preworkDone'},
    'series': {'running', 'runningUpdatedAt', 'userEdited', 'notesDoc'},
    'inbox': {'status', 'cardId', 'userEdited'},
}

def load(coll):
    p = os.path.join(ROOT, coll + '.json')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        txt = f.read().strip()
    data = json.loads(txt) if txt else {}
    if isinstance(data, list):
        data = {(d.get('id') or d.get('eventId') or d.get('key')): d for d in data}
    return data

def save(coll, data):
    p = os.path.join(ROOT, coll + '.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    with open(sys.argv[1], encoding='utf-8') as f:
        ops = json.load(f)
    if not isinstance(ops, list):
        print('ops file must be a JSON list'); sys.exit(2)
    cache = {}
    counts = {'applied': 0, 'skipped': 0, 'trimmed': 0}
    for o in ops:
        coll, oid, op = o.get('coll'), str(o.get('id', '')), o.get('op', 'merge')
        if coll not in COLLS or not oid:
            counts['skipped'] += 1; continue
        data = cache.setdefault(coll, load(coll))
        existing = data.get(oid)
        guarded = o.get('source') == 'sync'
        if guarded and coll == 'inbox':
            # the Reply list was retired on 2026-11-27: the scheduled tasks no longer write it
            counts['skipped'] += 1; continue
        if op == 'delete':
            if guarded:
                counts['skipped'] += 1; continue
            data.pop(oid, None); counts['applied'] += 1; continue
        patch = dict(o.get('patch') or {})
        if op == 'agenda_done':
            texts = {str(t).strip().lower() for t in (patch.get('texts') or [])}
            hit = 0
            if coll == 'meetings' and existing is not None:
                for item in (existing.get('agenda') or []):
                    if isinstance(item, dict) and str(item.get('text', '')).strip().lower() in texts and not item.get('done'):
                        item['done'] = True; hit += 1
            counts['applied' if hit else 'skipped'] += 1
            continue
        if guarded and coll == 'meta' and oid == 'categories':
            # the category list is KP's own (he edits it on the board): a scheduled task never writes it
            counts['skipped'] += 1; continue
        if guarded and coll == 'meta' and oid == 'projects' and existing is not None and isinstance(patch.get('items'), list):
            # a project keeps the category it has on the board
            had = {p.get('name'): p.get('cat') for p in (existing.get('items') or []) if isinstance(p, dict) and 'cat' in p}
            for p in patch['items']:
                if isinstance(p, dict) and p.get('name') in had:
                    p['cat'] = had[p['name']]
        if guarded and coll == 'cards' and 'cats' in patch:
            # categories: a scheduled task may give a card its first categories (ids from KP's list, two at
            # most); once a card has a "cats" list, even an empty one, only KP changes it
            valid = [k.get('id') for k in ((cache.setdefault('meta', load('meta')).get('categories') or {}).get('items') or []) if isinstance(k, dict)]
            want = list(dict.fromkeys(c for c in (patch['cats'] if isinstance(patch['cats'], list) else []) if c in valid))[:2]
            if (existing is not None and existing.get('cats') is not None) or not want:
                patch.pop('cats'); counts['trimmed'] += 1
                if not patch:
                    counts['skipped'] += 1; continue
            else:
                patch['cats'] = want
        if guarded and existing is not None and coll == 'cards' and 'connect' in patch:
            # connections are written once, in answer to the page's {"state": "pending"}; what the page
            # recorded with the request (when it was asked, which quick list it came from) is carried over
            was = existing.get('connect') if isinstance(existing.get('connect'), dict) else {}
            if was.get('state') == 'pending' and isinstance(patch['connect'], dict) and patch['connect'].get('state') in ('done', 'none'):
                patch['connect'] = {**{k: was[k] for k in ('askedAt', 'listId') if k in was}, **patch['connect']}
            else:
                patch.pop('connect')
                counts['trimmed'] += 1
                if not patch:
                    counts['skipped'] += 1; continue
        if guarded and existing is not None:
            if coll == 'cards' and op == 'set':
                # a sync never re-creates a card that exists (kept, done or dismissed): that would wipe the user's fields
                counts['skipped'] += 1; continue
            if coll == 'inbox' and (existing.get('userEdited') or existing.get('status') == 'handled'):
                counts['skipped'] += 1; continue
            if existing.get('userEdited') and coll in PROTECTED:
                before = len(patch)
                for k in PROTECTED[coll]:
                    patch.pop(k, None)
                if len(patch) < before:
                    counts['trimmed'] += 1
                if not patch:
                    counts['skipped'] += 1; continue
            if coll == 'meetings' and op == 'set':
                # a sync may rewrite a meeting but must carry the user's agenda forward
                for k in PROTECTED['meetings']:
                    if k in existing:
                        patch[k] = existing[k]
        if guarded and existing is not None and coll == 'meetings':
            # the day-before agenda doc and email draft are made once per meeting: a later run can
            # neither replace the record (that would orphan the doc and draft) nor clear the user's mark
            patch.pop('preworkDone', None)
            for once in ('prework', 'recap'):
                if (existing.get(once) or {}).get('at'):
                    patch.pop(once, None)
            if op == 'set':
                for k in ('prework', 'preworkDone', 'recap'):
                    if k in existing:
                        patch[k] = existing[k]
            if not patch:
                counts['skipped'] += 1; continue
        if guarded and existing is not None and coll == 'series':
            patch.pop('notesDoc', None)
            if op == 'set' and 'notesDoc' in existing:
                patch['notesDoc'] = existing['notesDoc']
            if not patch:
                counts['skipped'] += 1; continue
        if coll == 'notes' and guarded and existing is not None and 'qState' in existing:
            # which open questions the user kept or archived: a sync never loses these marks
            patch['qState'] = existing['qState']
        if coll == 'notes' and guarded and existing is not None and (existing.get('actions') or 'actions' in patch):
            # other people's to-dos live on the note: a sync may add new ones or mark one done,
            # but never drops one, never unticks one, and never brings back one the user moved to his board
            norm = lambda t: ' '.join(str(t or '').lower().split())
            merged = [dict(a) for a in (existing.get('actions') or [])]
            for a in (patch.get('actions') or []):
                if not isinstance(a, dict) or not a.get('text'):
                    continue
                hit = next((m for m in merged if (a.get('id') and m.get('id') == a.get('id')) or norm(m.get('text')) == norm(a.get('text'))), None)
                if hit is None:
                    merged.append(a)
                elif a.get('done') and not hit.get('done') and not hit.get('archived'):
                    hit['done'] = True; hit['doneAt'] = a.get('doneAt')
            patch['actions'] = merged
        if coll == 'cards':
            patch.setdefault('id', oid)
        if coll == 'meetings':
            patch.setdefault('eventId', oid)
        if coll == 'series':
            patch.setdefault('key', oid)
        if op == 'set' or existing is None:
            data[oid] = patch if op == 'set' else {**(existing or {}), **patch}
        else:
            data[oid] = {**existing, **patch}
        counts['applied'] += 1
    for coll, data in cache.items():
        save(coll, data)
    print('apply_ops: applied %(applied)d, skipped %(skipped)d, trimmed %(trimmed)d' % counts)

if __name__ == '__main__':
    main()
