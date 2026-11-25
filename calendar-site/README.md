# DUSC Club Calendar

The club's dates for the 2026–27 season, as two web pages:

- `index.html` — staff view: every date, with drafts, owners, people and notes, plus the dates still to be set.
- `families.html` — family view: only rows marked "Show to families" in the sheet that have a date and are not Draft. No owners, people, status or notes.

Each page has an "Add to my calendar" button that gives a subscription address (`calendar.ics` for staff, `families.ics` for families). A subscribed calendar follows later changes on its own.

## Where the dates come from

Dates are entered in the Google Sheet "DUSC Club Calendar 26-27". A scheduled task downloads the sheet a few times a day and runs `scripts/build_calendar.py`, which rewrites the files in `data/` and the two `.ics` files. Nothing here is edited by hand: to change a date, change the sheet.

In the sheet, each row needs a **Start date** (and an **End date** for anything longer than a day). **Show to families** = Yes puts a row on the family page once it is no longer marked Draft in the Status column.

`sync/calendar-sync.md` is the instruction the scheduled task follows. `scripts/make_site.py` regenerates the two pages if their design changes.
