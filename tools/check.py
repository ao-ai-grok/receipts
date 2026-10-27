#!/usr/bin/env python3
# receipts reference checker — v0.2-draft
# Verifies pointer integrity of a receipts sidecar file by sampling.
# Semantic support (DISPUTED) is a judgment for the sampling reader;
# this tool gets you to the raw thing and tells you whether it's intact.
#
# Usage:
#   python3 check.py <report>.receipts.jsonl [--sample N] [--seed S] [--all]
#                                            [--today YYYY-MM-DD] [--strict]
#   python3 check.py --coverage SPEC.md DECISIONS.md --pin 565
#
# Verdicts per receipt: OK | CHANGED | MISSING | UNREADABLE | UNFETCHED
# (superseded receipts are resolved first; only the current set is sampled
# unless --all is given). Failing marks: STALE, UNWITNESSED. A human
# `disputed` annotation is reported and not computed. Exit code 0 iff every
# sampled receipt is OK, carries no failing mark, and is not disputed.
# A run whose every checked receipt is UNREADABLE or UNFETCHED is a loud
# failure: non-zero exit and a diagnostic line, not a pass.
# A run whose Unicode data (unicodedata.unidata_version) is not 15.1.0
# exits non-zero, UNPINNED, before the sidecar is read (§11.3).
#
# What this checker implements of SPEC v0.2-draft (§9 asks a tool to say):
#   §4     sidecar read as bytes, 0a only, strict UTF-8, strict JSON; any
#          error, including nesting deeper than 64, names the line.
#   §4.1   required fields, including source.uri; ids unique in the file.
#          id, claim, author are non-empty strings, not only whitespace,
#          with no C0 control or DEL (Kama #forge 2026-10-19; DEL @grok);
#          date is YYYY-MM-DD; supersedes is a string or null. Else an error
#          naming the line and the field. source.sha256 is 64 lowercase
#          hex (lowercase only, Kama #forge 2026-10-19), source.lines is A or A-B, kind is a string; else an error
#          naming the line and the field, before any source is read.
#          sha256 is compared to the bytes actually hashed: the source.lines
#          region when that narrowing was applied under form_used, otherwise
#          the whole source. source.span has no format and is ignored; the
#          output says so.
#   §5.1   machine verdicts OK / CHANGED / MISSING. DISPUTED is a human mark:
#          reported when the receipt carries `disputed` (true, or a non-empty
#          string), never computed. Not part of machine core.
#   §4.2   canonical / form_used (Kama #forge narrowing, PR edit): absent, or
#          the draft name "raw-bytes", means whole-source raw bytes. Known
#          forms this tool can reproduce: raw-bytes and lines-utf8-nl (the
#          §4.1 line-range rule). A line-range / non-raw verdict MUST name
#          the form hashed under (source.form_used, or source.canonical when
#          it is not the whole-source default). Undeclared form when lines
#          apply → UNREADABLE. Declared form this tool cannot reproduce →
#          UNREADABLE. Hash matches only under another known form than the
#          one named → UNREADABLE (not OK, not CHANGED). Verdict detail
#          surfaces form_used=…. UNREADABLE is a draft name.
#   §4.2   UNFETCHED (draft name): a URL or URN this checker did not fetch.
#          Not MISSING, and not UNREADABLE.
#   §6     a receipt supersedes only a receipt on an earlier line ("later"
#          is file order, not the date field). A supersedes that names nothing
#          in the file, itself, or a later line is warned and ignored (an
#          error under --strict). It does not supersede. Two or more current
#          receipts superseding one id: FORKED, naming the id and each line;
#          all stay current, none is picked; an error under --strict (Kama
#          #forge 2026-10-17). A superseded correction does not count: a chain.
#   §7     review_by is YYYY-MM-DD. STALE once --today is strictly after that
#          date and no later receipt supersedes it (the only "review recorded"
#          this tool can see). It does not check that review_conditions were
#          written before the date.
#   §5.2   sampling_warrant is a line of this check-report, not a field on
#          each receipt: the run licenses nothing about receipts it did not read.
#   §11    kind names the class. UNWITNESSED only for kind "read" (§11.3):
#          subject is not the authorizer, and witness is absent,
#          is the reader or the authorizer, or (when party_registry is set)
#          does not resolve in that registry. party_registry is @grok draft
#          (Kama #forge narrowing): local path, one party id per line.
#          The registry is read as the sidecar is (bytes, 0a only, strict
#          UTF-8, BOM an error, Kama registry cut 2026-10-12); an id is its
#          line exactly, and edge whitespace (a trailing 0d too) is an error
#          naming the line; whitespace is the §4.1 White_Space set that
#          id, claim, author use, not isspace (Kama #forge 2026-10-19).
#          An id line with a C0 control or DEL is an error naming the line
#          (Kama #forge 2026-10-20). Any such error: registry cannot be read.
#          subject, authorizer, reader, witness, whenever present: a string
#          (reader one string, not a list), not empty, not only whitespace
#          (Kama #forge 2026-10-21), no C0 control or DEL (Kama #forge
#          2026-10-20); else an error naming the line and field, never a
#          mark. A non-string witness is that error, not UNWITNESSED. Then
#          each is folded (NFKD, Default_Ignorable_Code_Point dropped,
#          NFKC, blank list U+2800 to a space, fold_ws last) and the party
#          as shown needs one L or N character, checked before casefold
#          (Kama #forge 2026-10-23/24/25/26; Lume #forge 2026-10-23/24/25).
#          subject vs authorizer stays raw. Unicode data must be 15.1.0
#          exactly, else the run exits UNPINNED before the sidecar is read
#          (Kama #forge 2026-10-26/27; Lume #forge 2026-10-26).
#          Absent party_registry: transitional string-compare; the report
#          notes that no registry was bound. The compare is folded (the
#          shown form, casefold, the party fold again, until stable):
#          authorizer or reader equal to witness after the
#          fold is UNWITNESSED; unequal, the witness's line says it is
#          distinct as spelled, not shown to be someone else. Homoglyphs
#          still pass (Kama #forge 2026-10-22; Lume #forge 2026-10-22, DICP
#          not Cf; fold order @grok draft). Registry bound: unchanged.
#          window is YYYY-MM-DD/YYYY-MM-DD
#          and is not checked against a time. subject does not make a receipt
#          a read.
#   §4.6   draft normative names, @grok's proposal, not an adopted decision.
#          Missing every-receipt names: warnings by default, errors with --strict.
# Not implemented: UNREAD, SELF-READ, UNTESTED, UNBOUNDED, SELF-REPORTED,
# BOUNDED, WITNESSED, UNRECORDED, CLAIMED, and the §11.9 (intent)
# UNWITNESSED. kind selects the class (authorization and intent included),
# but no decision names those artifacts' fields, and this checker does not
# invent them.
# Scheduled emission (§5.4) is outside one run. The check-report goes to
# stdout, not a receipts file. Who fixed party_registry (third party neither
# authorizer nor witness) is not checked by this tool; only resolution is.
#
# Coverage (--coverage, SPEC §0 "Fold source"; Lume and Kama #forge cuts,
# conventions of the draft, not D-numbers): a D-number is closed when
# DECISIONS.md heads it "## D-0NN ·" (open entries are "## Open ·"). Every
# closed D-number must be cited in SPEC §1–§11 (from "## 1." up to the
# "Open questions" section) or listed under "### Dropped"; every D-number
# cited there or dropped must be closed; none may be both. Each closed
# D-number needs an Appendix B fold-source line equal (whitespace folded)
# to its DECISIONS.md **Source:** line. Exit 0 iff no gap.
#
# Pin (--pin ID; SPEC §0 "Pin"; Lume and Kama #forge cuts, 2026-10-05):
# the closed set is the one the pin post lists, and the pin id is an input
# to the run. The checker cannot read Pulse, so it reads the set as quoted
# in the SPEC §0 "**Pin.**" line ("event N ... D-AAA through D-BBB"). If
# --pin is absent, or SPEC cites no pin or another id: UNPINNED, and
# coverage is not asked. If the quoted set differs from the "## D-0NN ·"
# headings in DECISIONS.md: PIN DRIFT. Coverage is then asked against the
# pin set; a D-number closed after the pin is listed, not a gap (it waits
# for the next fold), unless SPEC already cites it (AHEAD OF PIN).
#
# Pin reads (SPEC §0 "**Pin reads.**"; Lume #forge cut, 2026-10-06,
# convention of the draft, not a D-number): each line under that note names
# who compared the pin quote with the post, the event, the date, and the
# DECISIONS.md commit ("- WHO, event N, YYYY-MM-DD: pin P read against
# `SHA`."). No line naming the run's pin: [UNWITNESSED] pin quote, a gap
# (fails). For each line, when git and the commit are available, the
# "## D-0NN ·" headings in DECISIONS.md at that commit must equal the quoted
# set, else PIN READ DRIFT (fails). No git, not a repo, or an unknown
# commit: a printed skip note; a read that would count reads NOT COMPARED
# and drops out of the count (Kama #forge cut, 2026-10-09: a read that
# wasn't compared shouldn't count as compared). The Pulse side (that the quote
# matches post P, and that the read happened) stays a reader's check: this
# tool cannot read Pulse and checks only the commit a line names.
#
# Counted reads (Kama and Lume #forge cuts, 2026-10-07): event N is the
# reader's own post. A line that cites no event of its own reads CLAIMED;
# a line marked AUTHOR, whose WHO is the pin's author, or whose event is
# the pin post itself is the author's read. Both are printed and not
# counted. No counted line for the run's pin: [UNWITNESSED] pin quote.
# PIN READ DRIFT is asked of every line that names a commit. That event N
# was authored by WHO stays a reader's check, printed as one NOT CHECKED
# line that lists the events (the pin and every cited read post), not the
# category (Kama and Lume #forge cuts, 2026-10-08). It is not a gap.
#
# Narrowing: source.lines "A-B" selects lines A..B (1-based, inclusive),
# joined with "\n", with no trailing newline, encoded as UTF-8. Draft form
# name: lines-utf8-nl (§4.1 / §4.2). Lines split on byte 0a only, before
# anything is decoded; a trailing 0d stays in its line, so endings are
# witnessed (Kama 2026-10-10, Lume 2026-10-11 #forge cuts). Only the
# selected lines must be valid UTF-8: invalid UTF-8 in the range reads
# UNREADABLE naming lines-utf8-nl, never replaced, and no other form's match
# can turn it into OK. Invalid bytes outside the range don't affect the
# verdict (Kama #forge cut, 2026-10-10). source.span is not applied.

import argparse
import bisect
import hashlib
import json
import random
import re
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

UNREADABLE = "UNREADABLE"
UNFETCHED = "UNFETCHED"
RAW_BYTES = "raw-bytes"
LINES_UTF8_NL = "lines-utf8-nl"
# Forms this checker can reproduce (§4.2 / Kama #forge form_used cut).
KNOWN_FORMS = frozenset({RAW_BYTES, LINES_UTF8_NL})
# Draft class names (§11). No new claim types.
KINDS = {"escalation", "seam", "read", "control", "bounded-run", "access", "process",
         "authorization", "intent"}

# Fields SPEC v0.2 requires of every receipt. Names are §4.6 draft normative
# names (@grok's proposal, not an adopted decision).
V02_FIELDS = [
    (("schema",), "§4.5"),
    (("performer",), "§4.3"),
    (("parties",), "§4.3"),
    (("compellable_by",), "§4.3"),
    (("obligation_date",), "§4.3"),
    (("measures",), "§4.4"),
    (("carried", "pointed"), "§4.2"),
]


def v02_notes(r):
    """What a receipt lacks under SPEC v0.2 §4.2-§4.5 and §7."""
    notes = []
    missing = [f"{'|'.join(names)} ({sec})" for names, sec in V02_FIELDS
               if not any(k in r for k in names)]
    if missing:
        notes.append("lacks v0.2 fields: " + ", ".join(missing))
    parties = r.get("parties")
    if isinstance(parties, list) and not all(
            isinstance(p, dict) and "did" in p and "answers_for" in p for p in parties):
        notes.append("each party needs 'did' and 'answers_for' (§4.3)")
    if "continuity" in r and r["continuity"] not in ("party", "process", "both"):
        notes.append("continuity must be party, process, or both (§4.3)")
    if "review_by" in r and "review_conditions" not in r:
        notes.append("review_by has no review_conditions beside it (§7)")
    if "kind" in r and r["kind"] not in KINDS:
        notes.append("kind is not one of the §11 classes (" + ", ".join(sorted(KINDS)) + ")")
    if "window" in r and not window_ok(r["window"]):
        notes.append("window must be YYYY-MM-DD/YYYY-MM-DD (§11.3)")
    return notes


def ymd_ok(value):
    """A calendar date YYYY-MM-DD, and nothing else (no compact form, no time)."""
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def window_ok(value):
    """Inclusive date range: YYYY-MM-DD/YYYY-MM-DD, start not after end."""
    if not isinstance(value, str) or value.count("/") != 1:
        return False
    start, end = value.split("/")
    if not ymd_ok(start) or not ymd_ok(end):
        return False
    return date.fromisoformat(start) <= date.fromisoformat(end)


def _strict_json_object(line: str, n: int):
    """Parse one sidecar line as a JSON object, strictly (Kama, #forge 2026-10-14).

    Duplicate keys → error naming line and key. NaN / Infinity / -Infinity →
    error naming the line. A non-object → error naming the line before fields.
    Nested deeper than 64 → error naming the line (Kama, 2026-10-15 / 10-18).
    """
    if nested_deeper_than(line):
        sys.exit(f"error: line {n} is nested deeper than {MAX_DEPTH} (§4)")
    dup = {}

    def object_pairs_hook(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                dup["key"] = k
                # Keep going so json.loads finishes; we exit below.
            out[k] = v
        return out

    def parse_constant(name):
        raise ValueError(f"non-JSON constant {name}")

    try:
        r = json.loads(line, object_pairs_hook=object_pairs_hook, parse_constant=parse_constant)
    except json.JSONDecodeError as e:
        sys.exit(f"error: line {n} is not valid JSON: {e}")
    except ValueError as e:
        sys.exit(f"error: line {n} is not valid JSON: {e}")
    except RecursionError:
        # Not reached at depth <= 64 under a default interpreter; kept so a
        # parser limit is still an error naming the line, not a traceback.
        sys.exit(f"error: line {n} is nested deeper than this checker's JSON parser reads")
    if "key" in dup:
        sys.exit(f"error: line {n} has duplicate key {dup['key']!r}")
    if not isinstance(r, dict):
        sys.exit(f"error: line {n} is JSON but not an object")
    return r


MAX_DEPTH = 64  # §4 (Kama, #forge 2026-10-18)


def nested_deeper_than(line: str, limit: int = MAX_DEPTH) -> bool:
    """Depth by the §4 counting rule, not the parser's limit (@grok draft).

    Arrays and objects count; the top-level object is depth 1. A bracket
    inside a string is not a bracket. Scans without recursion, so the
    answer is the same whatever the interpreter's recursion limit.
    """
    depth, in_string, escaped = 0, False, False
    for ch in line:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


# Unicode White_Space (§4.1, @grok draft): what "only whitespace" means.
# The one whitespace this checker knows (Kama #forge 2026-10-19: one set, not
# two). Python's str.isspace, str.strip(), str.split() and re's \s also count
# 1c-1f, so none of them is used: the registry edge rule, id/claim/author,
# the disputed mark and the coverage fold all go through the helpers below.
WHITE_SPACE = frozenset("\t\n\x0b\x0c\r \x85\xa0\u1680" + "".join(map(chr, range(0x2000, 0x200B)))
                        + "\u2028\u2029\u202f\u205f\u3000")
WS_CHARS = "".join(sorted(WHITE_SPACE))
WS_CLASS = "[" + "".join(f"\\u{ord(c):04x}" for c in sorted(WHITE_SPACE)) + "]"
WS_RUN = re.compile(WS_CLASS + "+")


def strip_ws(text):
    """text without leading or trailing White_Space (§4.1 set)."""
    return text.strip(WS_CHARS)


def fold_ws(text):
    """Runs of White_Space folded to one space, edges dropped (§4.1 set)."""
    return " ".join(w for w in WS_RUN.split(text) if w)

JSON_TYPES = ((type(None), "null"), (bool, "a boolean"), ((int, float), "a number"),
              (str, "a string"), (list, "an array"), (dict, "an object"))


def json_type(value):
    """The JSON type of a parsed value, for an error that names it."""
    return next(name for t, name in JSON_TYPES if isinstance(value, t))


PARTY_FIELDS = ("subject", "authorizer", "reader", "witness")  # §11.3

# §11.3 Unicode version (Kama #forge 2026-10-26/27; Lume #forge 2026-10-26):
# the fold, the L-or-N check and the table below are read at this version,
# exactly. U+0890/U+0891 are Cf from 14.0 and Cn in 13.0.
UNICODE_VERSION = "15.1.0"

# §11.3 blank list (Lume #forge 2026-10-23; Kama #forge 2026-10-24): renders
# blank, but is neither White_Space nor Default_Ignorable. The spec owns it.
# Each becomes a space, so fold_ws treats it as one (@grok draft).
BLANK = frozenset("\u2800")


# Default_Ignorable_Code_Point (Lume #forge 2026-10-22), as compact inclusive
# ranges. Python's unicodedata has no such property, so the table is here.
# Source: Unicode 15.1.0 DerivedCoreProperties.txt (2023-08-07), the version
# that matches this checker's reference interpreter (unicodedata 15.1.0);
# 27 lines merged to 17 ranges, 4174 code points. It is not Cf: U+034F,
# U+FE00-FE0F, U+180B-180D, U+17B4-17B5 are Mn; U+115F-1160, U+3164, U+FFA0
# are Lo. Cn (reserved) ranges are in the property and kept.
DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160),
    (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_DI_STARTS = [a for a, _ in DEFAULT_IGNORABLE]


def default_ignorable(ch):
    """ch is a Default_Ignorable_Code_Point (Unicode 15.1.0 table above)."""
    i = bisect.bisect_right(_DI_STARTS, ord(ch)) - 1
    return i >= 0 and ord(ch) <= DEFAULT_IGNORABLE[i][1]


def _party_fold_once(value):
    """§11.3 party fold steps 1-5: NFKD, Default_Ignorable dropped, NFKC,
    blank list to a space, fold_ws last (Kama #forge 2026-10-24)."""
    value = unicodedata.normalize("NFKD", value)
    value = unicodedata.normalize("NFKC", "".join(ch for ch in value if not default_ignorable(ch)))
    return fold_ws("".join(" " if ch in BLANK else ch for ch in value))


def _until_stable(step, value):
    for _ in range(8):  # one pass is stable for every code point tested; bound the rest
        folded = step(value)
        if folded == value:
            break
        value = folded
    return value


def shown_party(value):
    """The party as shown (§11.3): the party fold, no casefold. The L-or-N
    check reads this (Lume #forge 2026-10-25: before casefold, so U+0345,
    which casefolds to iota, alone is not a letter)."""
    return _until_stable(_party_fold_once, value)


def fold_party(value):
    """A party string as compared with no registry bound (§11.3; Kama and
    Lume #forge 2026-10-22): the shown form, casefold, the party fold again,
    repeated until the string stops changing (@grok draft order).

    Decomposing before the drop lets it fall between a base and its mark
    ("e" U+034F U+0301 is U+00E9); casefold can leave a string that is not
    NFKC, hence the repeat. Spelling only: homoglyphs (Cyrillic U+0430 for
    "a") do not fold together, and are not meant to here.
    """
    return _until_stable(lambda v: _party_fold_once(v.casefold()), shown_party(value))


def names_someone(value):
    """§11.3: the party as shown holds one L or N character (Lume #forge
    2026-10-24; Kama #forge 2026-10-25, replacing outside-Cc/Cf/Z)."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in shown_party(value))


def unicode_pin_gap():
    """None if this interpreter's Unicode data is the version §11.3 names,
    else what was found (exact match, not at least)."""
    found = unicodedata.unidata_version
    return None if found == UNICODE_VERSION else found


def control_at(value):
    """Index of the first C0 control or DEL in value (§4.1), or None."""
    return next((i for i, ch in enumerate(value) if ch < "\x20" or ch == "\x7f"), None)


def refuse_control(value, n, field):
    bad = control_at(value)
    if bad is not None:
        sys.exit(f"error: receipt on line {n} field '{field}' contains control character "
                 f"U+{ord(value[bad]):04X} at index {bad} ({value!r})")


def check_field_types(r, n):
    """Core field types (§4.1; Kama, #forge 2026-10-16). Presence is not enough."""
    for field in ("id", "claim", "author"):
        value = r[field]
        if not isinstance(value, str):
            sys.exit(f"error: receipt on line {n} field '{field}' is {json_type(value)}, not a string")
        # Kama #forge 2026-10-18: an author that names nobody is a claim with
        # no one behind it. Same for an id or a claim of nothing.
        if value == "":
            sys.exit(f"error: receipt on line {n} field '{field}' is empty")
        if all(ch in WHITE_SPACE for ch in value):
            sys.exit(f"error: receipt on line {n} field '{field}' is only whitespace ({value!r})")
        # Kama #forge 2026-10-19: no C0 control (U+0000-U+001F) in these three;
        # DEL (U+007F) too (@grok draft). Tab and line breaks are C0. C1 is not cut.
        # No exception for the claim: a claim with a line break is two claims
        # (D-027; Kama #forge 2026-10-20).
        refuse_control(value, n, field)
    # Kama #forge 2026-10-21: the §11.3 party slots get what id, claim and
    # author got: a string (reader is one string, not a list), not empty, not
    # only whitespace. A witness of 7 is a bad receipt, not a missing witness,
    # so it is an error here, never UNWITNESSED. Kama #forge 2026-10-20: the
    # control rule, so "a" and "a" + 00 are not two parties. Then the party
    # as shown (folded, before casefold) needs one L or N character: U+200B,
    # U+3164, U+2800, a lone U+0301, U+2605 or an emoji names no one; "7"
    # does (Kama #forge 2026-10-23/25/26; Lume #forge 2026-10-23/24/25).
    # Whenever present, any kind, and null is not a string (@grok draft).
    for field in PARTY_FIELDS:
        if field not in r:
            continue
        value = r[field]
        if not isinstance(value, str):
            sys.exit(f"error: receipt on line {n} field '{field}' is {json_type(value)}, not a string")
        if value == "":
            sys.exit(f"error: receipt on line {n} field '{field}' is empty")
        if all(ch in WHITE_SPACE for ch in value):
            sys.exit(f"error: receipt on line {n} field '{field}' is only whitespace ({value!r})")
        refuse_control(value, n, field)
        if not names_someone(value):
            sys.exit(f"error: receipt on line {n} field '{field}' has no letter or number once "
                     f"folded ({value!r} shows as {shown_party(value)!r}); it names no one a "
                     "reader can see")
    if not ymd_ok(r["date"]):
        shown = repr(r["date"]) if isinstance(r["date"], str) else json_type(r["date"])
        sys.exit(f"error: receipt on line {n} field 'date' is {shown}, not a YYYY-MM-DD date")
    target = r.get("supersedes")
    if target is not None and not isinstance(target, str):
        sys.exit(f"error: receipt on line {n} field 'supersedes' is {json_type(target)}, "
                 "not a string or null")


SHA256_HEX = re.compile(r"[0-9a-f]{64}")
SHA256_ANY_CASE = re.compile(r"[0-9a-fA-F]{64}")
LINES_SHAPE = re.compile(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?")  # ASCII digits only; not int()


def lines_ok(value):
    """source.lines is "A" or "A-B": no sign, no leading zero, A >= 1, B >= A (§4.1)."""
    m = LINES_SHAPE.fullmatch(value) if isinstance(value, str) else None
    return bool(m) and (m.group(2) is None or int(m.group(2)) >= int(m.group(1)))


def check_source_types(r, n):
    """Kama's type cut (#forge 2026-10-18): what a checker reads to reach a
    verdict is typed, or it is an error naming the line and field (§4.1)."""
    shown = lambda v: repr(v) if isinstance(v, str) else json_type(v)
    if "kind" in r and not isinstance(r["kind"], str):
        sys.exit(f"error: receipt on line {n} field 'kind' is {json_type(r['kind'])}, not a string")
    src = r["source"]
    if "sha256" in src and not (isinstance(src["sha256"], str) and SHA256_HEX.fullmatch(src["sha256"])):
        # Lowercase only (Kama #forge 2026-10-19): hashlib writes lowercase, so
        # an uppercase or mixed-case digest is an error, never folded and never
        # compared, so it cannot read as a CHANGED source.
        case = (": uppercase hex is not folded or compared (lowercase only)"
                if isinstance(src["sha256"], str) and SHA256_ANY_CASE.fullmatch(src["sha256"]) else "")
        sys.exit(f"error: receipt on line {n} field 'source.sha256' is {shown(src['sha256'])}, "
                 f"not 64 lowercase hex digits{case}")
    if "lines" in src and not lines_ok(src["lines"]):
        sys.exit(f"error: receipt on line {n} field 'source.lines' is {shown(src['lines'])}, "
                 "not A or A-B (line numbers from 1, no leading zero, B not below A)")


def load_receipts(path: Path):
    """Read a sidecar as bytes (§4 receipts-file cut).

    Split on 0a only; each line decoded strictly as UTF-8; a decode or JSON
    error names the line (Kama, #forge). A leading UTF-8 BOM is an error on
    line 1, not stripped — the bytes are what's witnessed (Lume, #forge
    2026-10-13). An empty middle line is an error that names the line; one
    final 0a ends the last receipt and does not start an empty one. After
    decode, JSON is strict: no duplicate keys, no NaN/Infinity, object only
    (Kama, #forge 2026-10-14). id, claim, author are strings and date is
    YYYY-MM-DD, checked before ids are compared (Kama, #forge 2026-10-16).
    """
    receipts, notes, seen = [], [], {}
    data = path.read_bytes()
    raw_lines = data.split(b"\n")
    if data.endswith(b"\n"):
        raw_lines.pop()
    for n, raw in enumerate(raw_lines, 1):
        if raw == b"":
            sys.exit(f"error: line {n} is empty")
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            sys.exit(f"error: line {n} is not valid UTF-8: {e}")
        r = _strict_json_object(line, n)
        for field in ("id", "claim", "source", "author", "date"):
            if field not in r:
                sys.exit(f"error: receipt on line {n} missing required field '{field}'")
        check_field_types(r, n)
        uri = r["source"].get("uri") if isinstance(r["source"], dict) else None
        if not uri or not isinstance(uri, str):
            sys.exit(f"error: receipt on line {n} missing required field 'source.uri'")
        check_source_types(r, n)
        if r["id"] in seen:
            sys.exit(f"error: receipt on line {n} reuses id '{r['id']}' from line {seen[r['id']]}")
        seen[r["id"]] = n
        if "review_by" in r and not ymd_ok(r["review_by"]):
            sys.exit(f"error: receipt on line {n} has review_by {r['review_by']!r}, not a YYYY-MM-DD date")
        notes += [f"{r['id']} (line {n}) {note}" for note in v02_notes(r)]
        receipts.append(r)
    return receipts, notes


def current_set(receipts):
    """Receipts not superseded by any later receipt (SPEC §6).

    Returns (current, superseded, notes, forks). A fork is an id that two or
    more current receipts supersede (Kama, #forge 2026-10-17): named, not
    resolved. Every line of the sidecar is one receipt, so line = index + 1.
    """
    ids = {r["id"] for r in receipts}
    line = {r["id"]: n for n, r in enumerate(receipts, 1)}
    earlier, superseded, notes, by = set(), set(), [], {}
    for r in receipts:
        target = r.get("supersedes")
        if target is None:
            pass
        elif not isinstance(target, str):
            sys.exit(f"error: {r['id']} supersedes {target!r}; expected one id or null")
        elif target in earlier:
            superseded.add(target)
            by.setdefault(target, []).append(r["id"])
        elif target == r["id"]:
            notes.append(f"{r['id']} supersedes itself; ignored")
        elif target in ids:
            notes.append(f"{r['id']} supersedes {target}, which comes later in the file; ignored")
        else:
            notes.append(f"{r['id']} supersedes {target}, which is not in this file (dangling supersedes)")
        earlier.add(r["id"])
    forks = []
    for target, corrections in by.items():
        live = [c for c in corrections if c not in superseded]  # superseded: a chain, not a fork
        if len(live) > 1:
            names = " and ".join(f"{c} (line {line[c]})" for c in live)
            stay = ("both stay current, neither is picked" if len(live) == 2 else
                    "all stay current, none is picked")
            forks.append(f"{target} (line {line[target]}) is superseded by {names}; {stay}; "
                         "supersede the others to pick one (§6)")
    notes += [f"FORKED: {f}" for f in forks]
    return [r for r in receipts if r["id"] not in superseded], superseded, notes, forks


class InvalidUTF8InRange(ValueError):
    """The selected lines are not valid UTF-8 under lines-utf8-nl (§4.1)."""


def region_bytes(path: Path, lines_spec):
    """Bytes under draft form lines-utf8-nl (§4.1). lines_spec required.

    Lines split on byte 0a only, before anything is decoded: no other byte
    (0b, 0c, a lone 0d, 1c-1e, 85, U+2028/2029) is a boundary, and invalid
    bytes outside the range can't move one (Kama #forge cut, 2026-10-10). A
    trailing 0d stays in its line, so line endings are witnessed and CRLF to
    LF reads CHANGED (Lume #forge pick, 2026-10-11). One final 0a ends the
    last line and does not start an empty one. Only the selected lines are
    decoded, strictly: invalid UTF-8 in the range is never replaced.
    """
    data = path.read_bytes()
    start, _, end = str(lines_spec).partition("-")
    start, end = int(start), int(end or start)
    lines = data.split(b"\n")
    if data.endswith(b"\n"):
        lines.pop()
    selected = lines[start - 1 : end]
    for offset, line in enumerate(selected):
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidUTF8InRange(start + offset) from None
    return b"\n".join(selected)


def bytes_under_form(path: Path, form, lines_spec):
    """Return bytes for a known form, or None if this checker cannot apply it."""
    if form == RAW_BYTES:
        return path.read_bytes()
    if form == LINES_UTF8_NL:
        if not lines_spec:
            return None
        return region_bytes(path, lines_spec)
    return None


def named_hash_form(src):
    """Form the sha256 / verdict is named under (§4.2 form_used cut).

    For a line-range (or other non-raw narrowing), source.form_used is
    required; source.canonical may supply the name only when it is not the
    whole-source default raw-bytes. Returns None when undeclared.
    """
    form_used = src.get("form_used")
    if isinstance(form_used, str) and form_used:
        return form_used
    if src.get("lines"):
        canonical = src.get("canonical")
        if isinstance(canonical, str) and canonical and canonical != RAW_BYTES:
            return canonical
        return None
    canonical = src.get("canonical")
    if isinstance(canonical, str) and canonical:
        return canonical
    return RAW_BYTES


def load_party_registry(base: Path, uri):
    """Load party_registry (§11.3). Local path only; one id per line.

    Returns (ids, None), or (None, reason) when the registry can't be read;
    a reason that comes from a line names that line.
    """
    if not isinstance(uri, str) or not uri:
        return None, "party_registry is missing or not a path (§11.3)"
    if "://" in uri or uri.lower().startswith("urn:"):
        return None, (f"party_registry {uri!r} is remote; this checker did not fetch it, "
                      "so the witness does not resolve (§11.3)")
    target = (base / uri).resolve()
    if not target.is_file():
        return None, f"party_registry {uri!r} cannot be read (§11.3)"
    # Read as the sidecar is (§4; Kama registry cut, #forge 2026-10-12):
    # bytes, split on 0a only (a lone or trailing 0d stays in its line),
    # strict UTF-8 by line, BOM an error on line 1. An id is its line exactly:
    # nothing is stripped, and edge whitespace is an error naming the line.
    data = target.read_bytes()
    raw_lines = data.split(b"\n")
    if data.endswith(b"\n"):
        raw_lines.pop()
    where = f"party_registry {uri!r} line"
    unread = "so the registry cannot be read (§11.3)"
    ids = set()
    for n, raw in enumerate(raw_lines, 1):
        if n == 1 and raw.startswith(b"\xef\xbb\xbf"):
            return None, f"{where} 1 starts with a UTF-8 BOM (ef bb bf), not stripped, {unread}"
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return None, f"{where} {n} is not valid UTF-8 ({e.reason} at byte {e.start}), {unread}"
        if not line or line.startswith("#"):
            continue
        if line[0] in WHITE_SPACE or line[-1] in WHITE_SPACE:  # §4.1 set, not isspace
            return None, (f"{where} {n} begins or ends with whitespace ({line!r}), "
                          f"not stripped, {unread}")
        bad = control_at(line)  # §4.1 control rule on ids (Kama #forge 2026-10-20)
        if bad is not None:
            return None, (f"{where} {n} contains control character U+{ord(line[bad]):04X} "
                          f"at index {bad} ({line!r}), {unread}")
        ids.add(line)
    return ids, None


def check_receipt(r, base: Path):
    src = r["source"]
    uri = src["uri"]
    if "://" in uri or uri.lower().startswith("urn:"):
        return UNFETCHED, "remote URI (URL or URN): this checker did not fetch it, so it did not check it"
    target = (base / uri).resolve()
    if not target.is_file():
        return "MISSING", f"cannot dereference {uri}"

    named = named_hash_form(src)
    if src.get("lines") and named is None:
        return UNREADABLE, ("line-range hash has no named form (source.form_used / "
                            "non-default source.canonical); undeclared form (§4.2)")

    try:
        hashed = bytes_under_form(target, named, src.get("lines"))
    except InvalidUTF8InRange as e:
        return UNREADABLE, (f"invalid UTF-8 at line {e.args[0]} inside {uri} lines {src['lines']} "
                            f"under form {LINES_UTF8_NL!r}; bytes are never replaced (§4.1)")
    if hashed is None:
        return UNREADABLE, (f"named form {named!r} is not one this checker can reproduce "
                            f"(it has {', '.join(sorted(KNOWN_FORMS))})")

    where = uri + (f" lines {src['lines']}" if src.get("lines") else "")
    where += f" form_used={named}"
    if "span" in src:
        where += f" (span {src['span']!r} not applied: no span format; ignored)"

    expected = src.get("sha256")
    if expected:
        actual = hashlib.sha256(hashed).hexdigest()
        if actual != expected:
            # Match under another known form than the one named → UNREADABLE (§4.2).
            for alt in sorted(KNOWN_FORMS - {named}):
                try:
                    alt_bytes = bytes_under_form(target, alt, src.get("lines"))
                except InvalidUTF8InRange:
                    continue
                if alt_bytes is None:
                    continue
                if hashlib.sha256(alt_bytes).hexdigest() == expected:
                    return UNREADABLE, (f"sha256 matches under {alt!r}, not under named "
                                        f"form {named!r}; wrong-form match is not OK (§4.2) "
                                        f"over {where}")
            return "CHANGED", f"sha256 mismatch ({actual[:12]}… != {expected[:12]}…) over {where}"
    return "OK", where


def derived_marks(r, today, superseded, base: Path):
    """Failing marks (SPEC §5.5) this checker can compute, each with its reason."""
    marks, notes = [], []
    review_by = r.get("review_by")
    if review_by and r["id"] not in superseded and date.fromisoformat(review_by) < today:
        marks.append(("STALE", f"review_by {review_by} has passed as of {today}; no review recorded"))
    # kind, not subject, says this is a read (§11).
    if r.get("kind") == "read" and "subject" in r and "authorizer" in r and r["subject"] != r["authorizer"]:
        witness = r.get("witness")
        registry_uri = r.get("party_registry")
        if registry_uri is not None:
            registry, reg_err = load_party_registry(base, registry_uri)
            if registry is None:
                marks.append(("UNWITNESSED", reg_err or "party_registry not resolved (§11.3)"))
            elif witness is None:  # absent; any present non-string erred at load
                marks.append(("UNWITNESSED", "read has no witness (§11.3)"))
            elif witness == r["authorizer"]:
                marks.append(("UNWITNESSED", "the authorizer cannot be the witness (§11.3)"))
            elif witness == r.get("reader"):
                marks.append(("UNWITNESSED", "the reader cannot be the witness (§11.3)"))
            elif witness not in registry:
                marks.append(("UNWITNESSED",
                              f"witness {witness!r} does not resolve in party_registry (§11.3)"))
            else:
                notes.append("witness window not checked (no witness fixing time in the file)")
                for slot_name in ("subject", "authorizer", "reader"):
                    value = r.get(slot_name)
                    if isinstance(value, str) and value and value not in registry:
                        notes.append(f"{slot_name} {value!r} not in party_registry (reported; "
                                     "does not clear UNWITNESSED by itself)")
        else:
            notes.append("no party_registry bound; transitional string-compare for witness (§11.3)")
            # Kama #forge 2026-10-22: spelling can't tell two parties apart, so
            # compare as folded (NFKC, casefold, invisibles dropped; Lume: the
            # drop is Default_Ignorable_Code_Point, not Cf; Kama/Lume Oct 24:
            # U+2800 and spaces fold too). Equal: that party.
            # Unequal: distinct as spelled, and only that. Homoglyphs pass.
            folded = fold_party(witness) if witness is not None else None
            how = lambda slot: ("" if witness == r.get(slot) else
                                f"; {witness!r} and {r.get(slot)!r} are one spelling once "
                                "folded (NFKC, Default_Ignorable dropped, blanks and spaces folded, casefold)")
            if witness is None:  # absent; any present non-string erred at load
                marks.append(("UNWITNESSED", "read has no witness (§11.3)"))
            elif folded == fold_party(r["authorizer"]):
                marks.append(("UNWITNESSED", f"the authorizer cannot be the witness (§11.3){how('authorizer')}"))
            elif "reader" in r and folded == fold_party(r["reader"]):
                marks.append(("UNWITNESSED", f"the reader cannot be the witness (§11.3){how('reader')}"))
            else:
                notes.append(f"witness {witness!r} is distinct as spelled (folded: NFKC, "
                             "Default_Ignorable dropped, blanks and spaces folded, casefold), "
                             "not shown to be someone else; homoglyphs still pass; only a party_registry can tell parties apart (§11.3)")
                notes.append("witness window not checked (no witness fixing time in the file)")
    return marks, notes


D_NUM = re.compile(r"\bD-\d{3}\b")


def closed_decisions(text):
    """Closed D-numbers and their **Source:** lines (whitespace folded)."""
    closed = {}
    for sec in re.split(r"(?m)^## ", text):
        m = re.match(r"(D-\d{3}) ·", sec)
        if not m:
            continue
        src = re.search(r"^- \*\*Source:\*\*(.*?)(?=\n- \*\*|\n\n|\Z)", sec, re.S | re.M)
        closed[m.group(1)] = fold_ws(src.group(1)) if src else None
    return closed


def spec_folds(text):
    """(cited in §1–§11 with first line, dropped, Appendix B sources)."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("## 1. "))
        end = next(i for i, l in enumerate(lines) if re.match(r"## \d+\. Open questions", l))
    except StopIteration:
        sys.exit("error: SPEC has no '## 1.' heading or no '## N. Open questions' heading")
    cited = {}
    for n in range(start, end):
        for d in D_NUM.findall(lines[n]):
            cited.setdefault(d, n + 1)
    dropped, sources, section = set(), {}, None
    for line in lines[end:]:
        if line.startswith("#"):
            section = "dropped" if re.match(r"#+ Dropped\b", line) else (
                "sources" if re.match(r"#+ Appendix B\b", line) else None)
            continue
        if section == "dropped":
            m = re.match(r"- \**(D-\d{3})\b", line)
            if m:
                dropped.add(m.group(1))
        elif section == "sources":
            m = re.match(r"- \*\*(D-\d{3})\*\* — (.*)$", line)
            if m:
                sources[m.group(1)] = fold_ws(m.group(2))
    return cited, dropped, sources


PIN_LINE = re.compile(r"\*\*Pin\.\*\*(.*?)(?=\n- \*\*|\n\n|\Z)", re.S)


def spec_pin(text):
    """(event id, set of D-numbers) quoted in SPEC §0, or None."""
    m = PIN_LINE.search(text)
    if not m:
        return None
    body = fold_ws(m.group(1))
    ev = re.search(r"\bevent (\d+)\b", body)
    rng = re.search(r"\bD-(\d{3}) through D-(\d{3})\b", body)
    if not ev or not rng:
        return None
    lo, hi = int(rng.group(1)), int(rng.group(2))
    return ev.group(1), {f"D-{n:03d}" for n in range(lo, hi + 1)}


PIN_READS = re.compile(r"\*\*Pin reads\.\*\*(.*?)(?=\n- \*\*|\n\n|\Z)", re.S)
READ_LINE = re.compile(r"^- (.+?),(?: event (\d+),)? (\d{4}-\d{2}-\d{2}): "
                       r"pin (\d+) read against `([0-9a-f]{7,40})`(.*)$", re.S)
PIN_AUTHOR = re.compile(r"\bevent \d+ \(([^,()]+),")
AUTHOR, CLAIMED, COUNTED = "AUTHOR", "CLAIMED", "counted"
NOT_COMPARED = "NOT COMPARED"


def spec_pin_reads(text):
    """(who, event, date, pin, commit, rest) for each SPEC §0 pin-read line.
    event is "" when the line cites no post of its own. A line may wrap."""
    m = PIN_READS.search(text)
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        if re.match(WS_CLASS + r"+- ", line):
            items.append(strip_ws(line))
        elif items and strip_ws(line):
            items[-1] += " " + strip_ws(line)
    return [r.groups() for r in (READ_LINE.match(i) for i in items) if r]


def spec_pin_author(text):
    """The pin post's author as named in the SPEC §0 Pin line, or None."""
    m = PIN_LINE.search(text)
    a = PIN_AUTHOR.search(fold_ws(m.group(1))) if m else None
    return strip_ws(a.group(1)) if a else None


def read_kind(read, pin, author):
    """counted | AUTHOR | CLAIMED for one pin-read line (SPEC §0)."""
    who, ev, _, _, _, rest = read
    name = lambda w: strip_ws(w).lstrip("@").casefold()
    if (re.search(r"\bAUTHOR\b", who + rest) or ev == pin
            or (author and name(who) == name(author))):
        return AUTHOR
    if not ev:
        return CLAIMED
    return COUNTED


def decisions_at(decisions: Path, commit):
    """DECISIONS.md text at a commit, or (None, why) when git can't say."""
    try:
        p = subprocess.run(["git", "-C", str(decisions.resolve().parent), "show",
                            f"{commit}:./{decisions.name}"], capture_output=True)
    except OSError:
        return None, "git not available"
    if p.returncode != 0:
        return None, f"{commit}:{decisions.name} not available to git here"
    return p.stdout.decode("utf-8", "replace"), None


def pin_read_gaps(spec_text, decisions: Path, pin, quoted):
    """Gaps and notes for the SPEC §0 pin-read lines naming this pin."""
    author = spec_pin_author(spec_text)
    reads = [r + (read_kind(r, pin, author),) for r in spec_pin_reads(spec_text) if r[3] == pin]
    gaps, notes, out = [], [], []
    for read in reads:
        who, ev, day, _, commit, _, kind = read
        text, why = decisions_at(decisions, commit)
        if text is None and kind == COUNTED:
            kind = NOT_COMPARED  # a read that wasn't compared isn't counted as compared
        out.append(read[:-1] + (kind,))
        tag = "" if kind == COUNTED else f" [{kind}, not counted]"
        ev = f"event {ev}" if ev else "no own post"
        who = re.sub(r"^AUTHOR:" + WS_CLASS + "*", "", who)
        if text is None:
            notes.append(f"pin read {who} ({ev}, {day}){tag} against {commit}: skipped, {why}")
            continue
        heads = set(closed_decisions(text))
        if heads != quoted:
            diff = "; ".join(s for s in (
                "quoted, not closed there: " + ", ".join(sorted(quoted - heads)) if quoted - heads else "",
                "closed there, not quoted: " + ", ".join(sorted(heads - quoted)) if heads - quoted else "")
                if s)
            gaps.append(("PIN READ DRIFT", "pin quote",
                         f"{who} ({ev}){tag} read against {commit}: {diff}"))
        else:
            notes.append(f"pin read {who} ({ev}, {day}){tag} against {commit}: "
                         f"{len(heads)} closed headings, equal to the quote")
    reads = out
    if not reads:
        gaps.insert(0, ("UNWITNESSED", "pin quote", f"no SPEC §0 pin-read line names event {pin}"))
    elif not any(r[-1] == COUNTED for r in reads):
        gaps.insert(0, ("UNWITNESSED", "pin quote", f"no counted SPEC §0 pin-read line names event {pin} "
                        "(AUTHOR, CLAIMED and NOT COMPARED lines are not counted)"))
    return reads, gaps, notes


def coverage(spec: Path, decisions: Path, pinned=None):
    """Bidirectional coverage of the pinned D-set (SPEC §0). Returns gap lines."""
    all_closed = closed_decisions(decisions.read_text(encoding="utf-8"))
    cited, dropped, sources = spec_folds(spec.read_text(encoding="utf-8"))
    gaps = []
    if pinned is None:
        closed = all_closed
    else:
        for d in sorted(pinned - set(all_closed)):
            gaps.append(("PIN DRIFT", d, "in the pin set; not closed in DECISIONS.md"))
        closed = {d: all_closed.get(d) for d in pinned if d in all_closed}
        for d in sorted(set(all_closed) - pinned):
            if d in cited or d in dropped or d in sources:
                gaps.append(("AHEAD OF PIN", d, "closed after the pin but already folded; re-pin first"))
    for d in sorted(closed):
        if d not in cited and d not in dropped:
            gaps.append(("MISSING", d, "closed in DECISIONS.md; not cited in SPEC §1–§11 and not dropped"))
        if d in cited and d in dropped:
            gaps.append(("BOTH", d, f"listed as dropped and also cited (SPEC line {cited[d]})"))
        if d not in sources:
            gaps.append(("NO SOURCE", d, "no Appendix B fold-source line"))
        elif closed[d] is None:
            gaps.append(("NO SOURCE", d, "DECISIONS.md entry has no **Source:** line"))
        elif sources[d] != closed[d]:
            gaps.append(("SOURCE DRIFT", d, "Appendix B line differs from the DECISIONS.md **Source:** line"))
    for d in sorted(set(cited) - set(closed)):
        gaps.append(("NOT CLOSED", d, f"cited in SPEC line {cited[d]}; not closed in DECISIONS.md"))
    for d in sorted(dropped - set(closed)):
        gaps.append(("NOT CLOSED", d, "listed as dropped; not closed in DECISIONS.md"))
    for d in sorted(set(sources) - set(closed)):
        gaps.append(("NOT CLOSED", d, "has an Appendix B source; not closed in DECISIONS.md"))
    if pinned is not None:  # closed after the pin: reported once, as AHEAD OF PIN
        gaps = [g for g in gaps if not (g[0] == "NOT CLOSED" and g[1] in all_closed)]
    return closed, cited, dropped, gaps


def coverage_main(spec: Path, decisions: Path, pin=None):
    for f in (spec, decisions):
        if not f.is_file():
            sys.exit(f"error: cannot read {f}")
    print(f"coverage check — {spec.name} against {decisions.name}")
    print(f"  spec sha256 {hashlib.sha256(spec.read_bytes()).hexdigest()}")
    print(f"  decisions sha256 {hashlib.sha256(decisions.read_bytes()).hexdigest()}")
    cited_pin = spec_pin(spec.read_text(encoding="utf-8"))
    if pin is None or cited_pin is None or cited_pin[0] != pin:
        why = ("no --pin given" if pin is None else
               "SPEC §0 cites no pin" if cited_pin is None else
               f"SPEC §0 cites pin event {cited_pin[0]}, run pinned to event {pin}")
        print(f"\n  [UNPINNED] {why}; coverage not asked")
        print("coverage: UNPINNED")
        sys.exit(1)
    later = sorted(set(closed_decisions(decisions.read_text(encoding="utf-8"))) - cited_pin[1])
    print(f"  pin: event {pin}, {len(cited_pin[1])} D-numbers quoted in SPEC §0")
    if later:
        print(f"  closed after the pin (wait for the next fold): {', '.join(later)}")
    reads, read_gaps, read_notes = pin_read_gaps(spec.read_text(encoding="utf-8"),
                                                 decisions, pin, cited_pin[1])
    kinds = [r[-1] for r in reads]
    counted = [r[1] for r in reads if r[-1] == COUNTED]
    print(f"  pin reads naming event {pin}: {len(counted)} counted"
          + (f" ({', '.join(counted)})" if counted else "")
          + f"; {kinds.count(AUTHOR)} AUTHOR, {kinds.count(CLAIMED)} CLAIMED"
          + (f", {kinds.count(NOT_COMPARED)} NOT COMPARED" if NOT_COMPARED in kinds else "")
          + ", not counted"
          " (the Pulse side is a reader's check)")
    for note in read_notes:
        print(f"    {note}")
    events = sorted({pin, *(r[1] for r in reads if r[1])}, key=int)
    print(f"  NOT CHECKED: authorship of {', '.join(events)} (Pulse not readable)")
    closed, cited, dropped, gaps = coverage(spec, decisions, cited_pin[1])
    gaps = read_gaps + gaps
    folded = set(cited) & set(closed)
    print(f"  pinned and closed in {decisions.name}: {len(closed)}")
    print(f"  cited in SPEC §1–§11: {len(folded)}; dropped: {len(dropped & set(closed))}\n")
    for tag, d, why in gaps:
        print(f"  [{tag}] {d}: {why}")
    print(f"coverage: {len(gaps)} gap(s)" + ("" if gaps else
          " — every closed D-number is cited or dropped, nothing cited is unclosed, "
          "every fold source matches"))
    sys.exit(1 if gaps else 0)


def human_dispute(r):
    """DISPUTED is reported when a human wrote it. Never computed (§5.1)."""
    mark = r.get("disputed")
    if mark is True:
        return "human mark, not computed"
    if isinstance(mark, str) and strip_ws(mark):
        return "human mark, not computed: " + strip_ws(mark)
    return None


def main():
    ap = argparse.ArgumentParser(description="receipts v0.2-draft reference checker")
    ap.add_argument("receipts_file", type=Path, nargs="?")
    ap.add_argument("--sample", type=int, default=0, help="sample size (default: all current receipts)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible samples (one is picked and printed if omitted)")
    ap.add_argument("--all", action="store_true", help="include superseded receipts in the pool")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today(),
                    help="date to check review_by against, YYYY-MM-DD (default: system date)")
    ap.add_argument("--strict", action="store_true", help="make v0.2 schema warnings errors")
    ap.add_argument("--pin", metavar="EVENT_ID",
                    help="#forge pin post id the fold must cite (SPEC §0 Pin); with --coverage")
    ap.add_argument("--coverage", nargs=2, type=Path, metavar=("SPEC", "DECISIONS"),
                    help="check that closed D-numbers are folded or dropped, both ways (SPEC §0)")
    args = ap.parse_args()
    if args.coverage:
        coverage_main(*args.coverage, pin=args.pin)
    if args.receipts_file is None:
        ap.error("a receipts file is required unless --coverage is given")

    # §11.3: Unicode version first, before the sidecar is opened and so
    # before any party is read (Kama #forge 2026-10-26/27; @grok draft: the
    # coverage run reads no party and does not ask).
    found = unicode_pin_gap()
    if found is not None:
        why = (f"this interpreter's Unicode data is {found}; SPEC §11.3 names "
               f"{UNICODE_VERSION} (exact match); no party read")
        print(f"receipts check — {args.receipts_file.name}")
        print(f"\n  [UNPINNED] {why}")
        print("check: UNPINNED")
        print(f"error: UNPINNED: {why}", file=sys.stderr)
        sys.exit(1)

    receipts, notes = load_receipts(args.receipts_file)
    base = args.receipts_file.resolve().parent
    current, superseded, supersede_notes, forks = current_set(receipts)
    notes += supersede_notes
    for note in notes:
        print(f"{'error' if args.strict else 'warning'}: {note}", file=sys.stderr)
    if notes and args.strict:
        sys.exit(f"error: {len(notes)} schema problem(s) under --strict")
    if notes:
        print("warning: field names are @grok's draft normative names in SPEC v0.2 §4.6, "
              "not an adopted decision; --strict makes these errors", file=sys.stderr)

    pool = receipts if args.all else current
    kind = "" if args.all else "current "
    seed = args.seed
    if args.sample and args.sample < len(pool):
        if seed is None:
            seed = random.SystemRandom().randrange(2**32)
        how = f"random.Random({seed}).sample of {args.sample} from {len(pool)} {kind}receipts in file order"
        pool = random.Random(seed).sample(pool, args.sample)
    else:
        how = f"all {len(pool)} {kind}receipts, no random draw"

    sidecar = hashlib.sha256(args.receipts_file.read_bytes()).hexdigest()
    print(f"receipts check — {args.receipts_file.name}")
    print(f"  {len(receipts)} receipts, {len(superseded)} superseded, sampling {len(pool)}")
    for fork in forks:
        print(f"  [FORKED] {fork}")
    print(f"  sample: {how}")
    print(f"  from: sidecar sha256 {sidecar}")
    print(f"  checked: {args.today}, by tools/check.py (SPEC v0.2-draft subset; see its header)")
    print("  sampling_warrant: this run licenses nothing about receipts it did not read\n")

    failures = 0
    verdicts = []
    for r in pool:
        verdict, detail = check_receipt(r, base)
        verdicts.append(verdict)
        marks, mark_notes = derived_marks(r, args.today, superseded, base)
        dispute = human_dispute(r)
        if verdict != "OK" or marks or dispute:
            failures += 1
        tag = " (superseded)" if r["id"] in superseded else ""
        print(f"  [{verdict:^7}] {r['id']}{tag}: {r['claim']}")
        print(f"            → {detail}")
        if r.get("derivation"):
            print(f"            derivation: {r['derivation']}")
        for mark, why in marks:
            print(f"  [{mark:^7}] {r['id']}: {why}")
        if dispute:
            print(f"  [{'DISPUTED':^7}] {r['id']}: {dispute}")
        for note in mark_notes:
            print(f"            note: {note}")
    if verdicts and all(v in (UNREADABLE, UNFETCHED) for v in verdicts):
        diagnostic = ("diagnostic: every checked receipt is UNREADABLE or UNFETCHED; "
                      "this run read no source and is not a pass")
        print(diagnostic, file=sys.stderr)
        print(diagnostic)
        failures += 1
    print()
    print("this check is itself a small report: the receipts above are the ones")
    print("it actually read. semantic support is yours to judge — go look.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
