# DUSC Action Board — data

This private repo is the database for the DUSC Action Board (the page at dusc.netlify.app).

- `data/cards.json` — to-dos, keyed by card id. Statuses: todo · doing · waiting · done.
- `data/notes.json` — digests of KP's Drive meeting notes.
- `data/inbox.json` — email threads that need KP, from the two-hour sweep.
- `data/meetings.json` — upcoming calendar events with prep and agendas (key = Google event id).
- `data/series.json` — recurring meeting groups: where things stand, running notes.
- `data/meta.json` — `sync` (morning Drive sync) and `inbox` (email sweep) status and the state-of-play summary.
- `scripts/apply_ops.py` — applies a list of changes to the data files, with guards so an automated sync never overwrites something KP changed by hand.

The page writes directly to `data/*.json` with a fine-grained token (Contents: read & write). The scheduled tasks clone the repo, run `apply_ops.py`, commit and push.

## Hosting

Netlify publishes only the `site/` folder (see `netlify.toml`). The `data/` folder is never served.
