#!/usr/bin/env python3
"""Apply a list of operations to the board's data files.

Usage:  python3 scripts/apply_ops.py ops.json
ops.json = [ {"coll": "cards", "id": "mlk-tuesday-space", "op": "merge", "patch": {...}, "source": "sync"}, ... ]

op: "set" (replace the whole doc), "merge" (shallow-merge fields), "delete", and
"agenda_done" (meetings only; patch {"texts": [...]} marks the agenda items with those exact texts as
done and changes nothing else - safe on agendas the user has edited).
source "sync" (the scheduled tasks) is guarded: it never deletes, never touches an inbox item the
user has handled, and never overrides fields the user has edited (userEdited: true) on cards,
meetings or series. On notes it can add to the "actions" list (other people's to-dos) or mark one
done, but never removes or unticks one. The page (source "user") has no guard.
Prints a one-line summary. Exit code 0 on success.
"""
import json, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
COLLS = ['cards', 'notes', 'inbox', 'meetings', 'series', 'meta']
PROTECTED = {
    'cards': {'status', 'title', 'owner', 'due', 'note', 'priority', 'pinned', 'pinnedAt', 'waitingOn', 'waitingSince', 'doneAt', 'area', 'userEdited'},
    'meetings': {'agenda', 'agendaUpdatedAt', 'agendaSentAt', 'userEdited', 'skipAgenda'},
    'series': {'running', 'runningUpdatedAt', 'userEdited'},
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
        if guarded and existing is not None:
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
                elif a.get('done') and not hit.get('done'):
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
