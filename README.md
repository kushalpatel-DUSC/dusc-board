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

`index.html` at the top of this repo is the board. It reads the live data in `data/` straight from
GitHub, so anyone with the link sees the current board with no sign-in. A device only needs a GitHub
token (Contents: read and write on this repo) to make changes; it is pasted once into the board's
"Connect to edit" box and kept in that browser.
