#!/usr/bin/env python3
"""DUSC meeting notes docs: build the Google Docs update_doc arguments for the house format.

Every index is worked out here, so nothing is counted by hand.

  python3 notes_doc.py anchor DOC.json [--text "Meeting log"]
      DOC.json is a saved mcp__Google_Docs__read_doc result. Prints the revisionId, the tab id and
      the index a new meeting section goes at (the end of the "Meeting log" heading), plus whether
      the open-items placeholder is still in the doc.

  python3 notes_doc.py section --at I --revision REV --spec SPEC.json [--tab T] [--font F]
      Prints {"requests": [...], "writeControl": {...}} for mcp__Google_Docs__update_doc: one meeting
      section inserted right after the paragraph that ends at I + 1 (I is what `anchor` prints).
      SPEC.json for an upcoming meeting:
        {"dateLabel": "Mon Nov 30, 2026", "meeting": "Finance Weekly", "attendees": "Nirmala, Kushal",
         "agenda": ["October package: sign-off", "Audit: adjusting entries"],
         "last": {"title": "Finance Weekly, Nov 16 (Gemini notes)", "url": "https://docs.google.com/..."}}
      SPEC.json for a meeting that already happened (no agenda; the recap is written straight in):
        {"dateLabel": "Tue Nov 24, 2026", "meeting": "Recurring Finance meeting", "attendees": "...",
         "recap": "Two or three sentences.", "decisions": ["..."], "actions": ["Nirmala: ..."],
         "notes": {"title": "Gemini notes", "url": "https://docs.google.com/..."}}

  python3 notes_doc.py blocks --at I --mode after|start --spec BLOCKS.json [--revision REV] [--tab T] [--font F]
      The same for a free list of blocks (used to set a doc up for the first time).

  python3 notes_doc.py restyle DOC.json
      Explicit heading styles for every heading already in a doc (used once, when a doc joins the format).

  python3 notes_doc.py placeholders "Mon Nov 30, 2026"
      Prints the three placeholder texts of that meeting's section and the open-items placeholder.
      After the meeting they are filled with replaceAllText, which needs no index.
"""
import argparse, json, re, sys

OPEN_PLACEHOLDER = "(add a new open item here)"
def rgb(h):
    return {"color": {"rgbColor": {"red": round(int(h[1:3], 16) / 255, 4), "green": round(int(h[3:5], 16) / 255, 4), "blue": round(int(h[5:7], 16) / 255, 4)}}}

# The club's look, taken from the Ops Meeting notes doc: Montserrat headings, navy and orange.
NAVY, ORANGE, GRAY = rgb("#013471"), rgb("#FA6B0D"), rgb("#6B7280")
PRESET = {"num": "NUMBERED_DECIMAL_ALPHA_ROMAN", "bul": "BULLET_DISC_CIRCLE_SQUARE", "chk": "BULLET_CHECKBOX"}
BODY_RESET = "bold,italic,underline,strikethrough,smallCaps,backgroundColor,foregroundColor,fontSize,weightedFontFamily,baselineOffset,link"

def _ts(size, color, bold=True, family="Montserrat"):
    return {"bold": bold, "italic": False, "fontSize": {"magnitude": size, "unit": "PT"}, "weightedFontFamily": {"fontFamily": family, "weight": 400}, "foregroundColor": color}

# Headings are styled explicitly as well as by name, so a section looks the same in every doc
# whatever that doc's own heading styles are.
LABEL_TS = _ts(9, ORANGE)
HEAD_TS = {"TITLE": _ts(24, NAVY), "SUBTITLE": _ts(9.5, GRAY, bold=False, family="Arial"), "HEADING_1": _ts(17, NAVY), "HEADING_2": _ts(13, ORANGE), "HEADING_3": _ts(10.5, NAVY)}
HEAD_FIELDS = "bold,italic,fontSize,weightedFontFamily,foregroundColor"


def u16(s):
    return len(s.encode("utf-16-le")) // 2


def key_of(date_label):
    """'Mon Nov 30, 2026' -> 'Nov 30, 2026' (the part the placeholders carry)."""
    return re.sub(r"^[A-Za-z]{3,9},?\s+(?=[A-Z][a-z]{2}\s)", "", date_label.strip())


def placeholders(date_label):
    k = key_of(date_label)
    return {"decisions": "(decisions, %s)" % k, "actions": "(action items, %s)" % k,
            "recap": "(recap from the Gemini notes, %s)" % k, "open": OPEN_PLACEHOLDER}


class P:
    def __init__(self, text, style="NORMAL_TEXT", lst=None, level=0, runs=None, below=None, meta=False):
        self.text = text.replace("\n", " ").replace("\t", " ")
        self.style, self.lst, self.level = style, lst, level
        self.runs = runs or []          # (start, length, textStyle, fields) relative to the visible text
        self.below = below
        self.meta = meta                # a small grey line under the date heading (attendees, source)


def owner_run(text):
    m = re.match(r"^([A-Z][A-Za-z .&/+'-]{0,40}?):\s", text)
    return [(0, u16(m.group(1)) + 1, {"bold": True}, "bold")] if m else []


def to_paras(blocks):
    out = []
    for b in blocks:
        k = b["k"]
        if k == "label":
            t = b["t"]; out.append(P(t, runs=[(0, u16(t), LABEL_TS, HEAD_FIELDS)]))
        elif k == "title":
            out.append(P(b["t"], "TITLE"))
        elif k == "subtitle":
            out.append(P(b["t"], "SUBTITLE"))
        elif k in ("h1", "h2", "h3"):
            out.append(P(b["t"], "HEADING_" + k[1]))
        elif k == "attendees":
            out.append(P("Attendees: " + b["t"], meta=True))
        elif k == "p":
            out.append(P(b["t"], below=b.get("below")))
        elif k == "link":
            pre = b.get("pre", ""); t = pre + b["t"]
            out.append(P(t, runs=[(u16(pre), u16(b["t"]), {"link": {"url": b["url"]}}, "link")], meta=True))
        elif k in PRESET:
            items = b["items"] or [""]
            for i, it in enumerate(items):
                it = {"t": it} if isinstance(it, str) else it
                subs = it.get("sub") or []
                last = i == len(items) - 1
                out.append(P(it["t"], lst=k, level=0, runs=owner_run(it["t"]) if b.get("owners") else []))
                for j, s in enumerate(subs):
                    out.append(P(s, lst=k, level=1))
        else:
            raise SystemExit("unknown block kind: %r" % k)
    return out


def build(blocks, at, mode="after", revision=None, tab=None, font=None, reset=True):
    paras = to_paras(blocks)
    raw = [("\t" * p.level) + p.text for p in paras]
    text = ("\n" + "\n".join(raw)) if mode == "after" else ("\n".join(raw) + "\n")
    pos = at + 1 if mode == "after" else at
    for p, r in zip(paras, raw):
        p.s = pos; p.tabs = p.level; p.e = pos + u16(r) + 1; pos = p.e      # e is just past the paragraph's newline

    def loc(d):
        if tab: d["tabId"] = tab
        return d

    def rng(s, e):
        return loc({"startIndex": s, "endIndex": e})

    reqs = [{"insertText": {"location": loc({"index": at}), "text": text}}]

    def spans(key):                     # merge neighbouring paragraphs that share key(p) into one range
        res = []
        for p in paras:
            k = key(p)
            if res and res[-1][0] == k and res[-1][2] == p.s: res[-1][2] = p.e
            else: res.append([k, p.s, p.e])
        return res

    if reset:       # text put in next to existing text copies its paragraph and text style: clear both over the whole insert first
        reqs.append({"updateParagraphStyle": {"range": rng(paras[0].s, paras[-1].e), "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
        reqs.append({"updateTextStyle": {"range": rng(paras[0].s, paras[-1].e), "textStyle": {}, "fields": BODY_RESET}})
    for style, s, e in spans(lambda p: p.style):
        if style != "NORMAL_TEXT":
            reqs.append({"updateParagraphStyle": {"range": rng(s, e), "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})
            reqs.append({"updateTextStyle": {"range": rng(s, e - 1), "textStyle": HEAD_TS[style], "fields": HEAD_FIELDS}})
    for meta, s, e in spans(lambda p: p.meta):
        if meta: reqs.append({"updateTextStyle": {"range": rng(s, e - 1), "textStyle": {"foregroundColor": GRAY}, "fields": "foregroundColor"}})
    if font:
        reqs.append({"updateTextStyle": {"range": rng(paras[0].s, paras[-1].e), "textStyle": {"weightedFontFamily": {"fontFamily": font}}, "fields": "weightedFontFamily"}})
    for p in paras:
        for (a, n, ts, fields) in p.runs:
            if n > 0:
                reqs.append({"updateTextStyle": {"range": rng(p.s + p.tabs + a, p.s + p.tabs + a + n), "textStyle": ts, "fields": fields}})
    for below, s, e in spans(lambda p: p.below):
        if below:
            reqs.append({"updateParagraphStyle": {"range": rng(s, e), "paragraphStyle": {"spaceBelow": {"magnitude": below, "unit": "PT"}}, "fields": "spaceBelow"}})
    # lists last, bottom-up: making a list removes the leading tabs of nested lines, which shifts everything after it
    groups = []
    for p in paras:
        if p.lst and groups and groups[-1][0] == p.lst and groups[-1][2] == p.s: groups[-1][2] = p.e
        elif p.lst: groups.append([p.lst, p.s, p.e])
    for kind, s, e in reversed(groups):
        reqs.append({"createParagraphBullets": {"range": rng(s, e), "bulletPreset": PRESET[kind]}})
    out = {"requests": reqs}
    if revision: out["writeControl"] = {"requiredRevisionId": revision}
    return out, text


def section_blocks(spec):
    head = [{"k": "h2", "t": "%s · %s" % (spec["dateLabel"], spec["meeting"])}]
    if spec.get("attendees"): head.append({"k": "attendees", "t": spec["attendees"]})
    if "recap" in spec:                                            # a meeting that already happened
        b = list(head)
        if spec.get("notes"): b.append({"k": "link", "pre": "Source: ", "t": spec["notes"]["title"], "url": spec["notes"]["url"]})
        b += [{"k": "h3", "t": "Recap"}, {"k": "p", "t": spec["recap"]}, {"k": "h3", "t": "Decisions"}]
        b.append({"k": "bul", "items": spec["decisions"]} if spec.get("decisions") else {"k": "p", "t": "None recorded."})
        b.append({"k": "h3", "t": "Action items"})
        b.append({"k": "bul", "items": spec["actions"]} if spec.get("actions") else {"k": "p", "t": "None recorded."})
        return b
    ph = placeholders(spec["dateLabel"])
    b = list(head)
    if spec.get("last"): b.append({"k": "link", "pre": "Last time: ", "t": spec["last"]["title"], "url": spec["last"]["url"]})
    b += [{"k": "h3", "t": "Agenda and notes"}, {"k": "num", "items": [{"t": a, "sub": [""]} for a in (spec.get("agenda") or ["Open items from last time"])]},
          {"k": "h3", "t": "Add your items"}, {"k": "bul", "items": [""]},
          {"k": "h3", "t": "Decisions"}, {"k": "bul", "items": [ph["decisions"]]},
          {"k": "h3", "t": "Action items"}, {"k": "chk", "items": [ph["actions"]]},
          {"k": "h3", "t": "Recap"}, {"k": "p", "t": ph["recap"]}]
    return b


def body_of(doc):
    """(tabId or None, body content list) of the first tab."""
    if isinstance(doc, list): doc = json.loads(doc[0]["text"])       # the app's saved tool-result wrapper
    if isinstance(doc.get("content"), dict) and "documentId" in doc["content"]: doc = doc["content"]
    if "tabs" in doc and doc["tabs"]:
        t = doc["tabs"][0]
        return doc, t["tabProperties"]["tabId"], t["documentTab"]["body"]["content"]
    return doc, None, doc["body"]["content"]


def para_text(el):
    return "".join(e.get("textRun", {}).get("content", "") for e in el.get("paragraph", {}).get("elements", []))


def cmd_anchor(a):
    doc, tab, content = body_of(json.load(open(a.doc)))
    want = a.text.strip().lower(); hit = None; has_open = False; heads = []
    for el in content:
        if "paragraph" not in el: continue
        t = para_text(el).strip()
        if OPEN_PLACEHOLDER in t: has_open = True
        st = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", "")
        if st.startswith("HEADING") or st == "TITLE": heads.append((el.get("startIndex", 1), st, t[:70]))
        if hit is None and t.lower() == want: hit = el
    print("revisionId:", doc.get("revisionId")); print("tabId:", tab)
    for h in heads[:14]: print("  heading @%s %s %s" % h)
    if hit is None:
        print('NO "%s" paragraph in this doc: do not insert; say so in the meeting\'s prework note.' % a.text); sys.exit(3)
    print("anchor paragraph: [%d, %d) %r" % (hit["startIndex"], hit["endIndex"], para_text(hit).strip()))
    print("--at", hit["endIndex"] - 1)
    print("open-items placeholder present:", has_open)


def cmd_restyle(a):
    """Give a doc that is already laid out in the format the club's look. Touches only the label, the
    headings and the small lines that start with Attendees:, Source: or Last time:."""
    doc, tab, content = body_of(json.load(open(a.doc))); reqs = []

    def add(s0, e0, ts, fields):
        r = {"startIndex": s0, "endIndex": e0}
        if tab: r["tabId"] = tab
        last = reqs[-1]["updateTextStyle"] if reqs else None
        if last and last["fields"] == fields and last["textStyle"] == ts and last["range"]["endIndex"] == s0: last["range"]["endIndex"] = e0
        else: reqs.append({"updateTextStyle": {"range": r, "textStyle": ts, "fields": fields}})

    first = True
    for el in content:
        if "paragraph" not in el: continue
        st = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", ""); t = para_text(el)
        if a.until and el["startIndex"] >= a.until: break
        if first and t.strip() == "DOWNTOWN UNITED SOCCER CLUB": add(el["startIndex"], el["endIndex"] - 1, LABEL_TS, HEAD_FIELDS)
        elif st in HEAD_TS and t.strip(): add(el["startIndex"], el["endIndex"] - 1, HEAD_TS[st], HEAD_FIELDS)
        elif st == "NORMAL_TEXT" and re.match(r"^(Attendees|Source|Last time): ", t):
            for run in el["paragraph"]["elements"]:
                tr = run.get("textRun", {})
                if tr.get("content", "").strip() and not tr.get("textStyle", {}).get("link"):
                    add(run["startIndex"], run["endIndex"] - (1 if tr["content"].endswith("\n") else 0), {"foregroundColor": GRAY}, "foregroundColor")
        first = False
    print(json.dumps({"requests": reqs, "writeControl": {"requiredRevisionId": doc.get("revisionId")}}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("anchor"); s.add_argument("doc"); s.add_argument("--text", default="Meeting log")
    for name in ("section", "blocks"):
        s = sub.add_parser(name); s.add_argument("--at", type=int, required=True); s.add_argument("--spec", required=True)
        s.add_argument("--revision"); s.add_argument("--tab"); s.add_argument("--font")
        if name == "blocks":
            s.add_argument("--mode", choices=["after", "start"], default="after"); s.add_argument("--no-reset", action="store_true")
    s = sub.add_parser("placeholders"); s.add_argument("dateLabel")
    s = sub.add_parser("restyle"); s.add_argument("doc"); s.add_argument("--until", type=int)
    a = ap.parse_args()
    if a.cmd == "anchor": return cmd_anchor(a)
    if a.cmd == "restyle": return cmd_restyle(a)
    if a.cmd == "placeholders": return print(json.dumps(placeholders(a.dateLabel), indent=1, ensure_ascii=False))
    spec = json.load(open(a.spec))
    blocks = section_blocks(spec) if a.cmd == "section" else spec
    out, _ = build(blocks, a.at, getattr(a, "mode", "after"), a.revision, a.tab, a.font, reset=not getattr(a, "no_reset", False))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
