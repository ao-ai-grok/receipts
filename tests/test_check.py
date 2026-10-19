# Tests for tools/check.py. Standard library only:
#   python3 -m unittest
# Each fixture is a small sidecar written to a temporary directory, one per
# checker gap listed in PR #2 ("Spec vs checker gaps").

import hashlib
import os
import shutil
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "tools" / "check.py"
EXAMPLE = ROOT / "examples" / "rounding-toward-alarming" / "report.md.receipts.jsonl"
RAW = b"line one\nline two\nline three\n"

# Every field SPEC v0.2 requires, under the names §4.6 suggests.
V02 = {"schema": "receipts/0.2-draft", "performer": "a@example.test",
       "parties": [{"name": "a@example.test", "did": "wrote", "answers_for": "claim"}],
       "compellable_by": "the reader", "obligation_date": "2026-09-01",
       "measures": "lines in raw.txt", "carried": [], "pointed": ["raw.txt"]}


def receipt(id, supersedes=None, v02=True, **source):
    r = {"id": id, "claim": f"claim {id}", "source": {"uri": "raw.txt", **source},
         "author": "a@example.test", "date": "2026-09-01", "supersedes": supersedes}
    return {**V02, **r} if v02 else r


def run(receipts, *args, raw=RAW):
    """Write a sidecar (list of dicts, or raw text) beside raw.txt and check it."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "raw.txt").write_bytes(raw)
        sidecar = Path(d) / "report.md.receipts.jsonl"
        if isinstance(receipts, (bytes, bytearray)):
            sidecar.write_bytes(bytes(receipts))
        elif isinstance(receipts, str):
            sidecar.write_text(receipts)
        else:
            sidecar.write_text("".join(json.dumps(r) + "\n" for r in receipts))
        return subprocess.run([sys.executable, str(CHECK), str(sidecar), "--today", "2026-09-27", *args],
                              capture_output=True, text=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def not_a_checkout(root):
    """Why root is not a git checkout pin reads can be compared in, or None."""
    if not shutil.which("git"):
        return "not a git checkout (no git binary): pin reads can't be compared"
    p = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if p.returncode != 0 or Path(p.stdout.strip()).resolve() != Path(root).resolve():
        return "not a git checkout (git rev-parse fails here): pin reads can't be compared"
    return None


class Example(unittest.TestCase):
    """Backward compatibility: the worked example gives the same verdicts as v0.1."""

    def test_example_verdicts_unchanged(self):
        p = subprocess.run([sys.executable, str(CHECK), str(EXAMPLE)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("[  OK   ] r-001", p.stdout)
        self.assertIn("[  OK   ] r-003", p.stdout)
        self.assertIn("[MISSING] r-004", p.stdout)
        self.assertNotIn("r-002", p.stdout)

    def test_example_all_shows_superseded(self):
        p = subprocess.run([sys.executable, str(CHECK), str(EXAMPLE), "--all"], capture_output=True, text=True)
        self.assertIn("[  OK   ] r-002 (superseded)", p.stdout)
        self.assertEqual(p.returncode, 1)


class Gap1Canonical(unittest.TestCase):
    def test_declared_canonical_form_is_never_ok(self):
        p = run([receipt("r-1", sha256=sha(RAW), canonical="nfc-text")])
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("'nfc-text'", p.stdout)
        self.assertIn("not one this checker can reproduce", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_absent_canonical_means_raw_bytes(self):
        p = run([receipt("r-1", sha256=sha(RAW))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertNotIn("diagnostic:", p.stderr)
        self.assertEqual(p.returncode, 0)

    def test_named_raw_bytes_is_ok(self):
        p = run([receipt("r-1", sha256=sha(RAW), canonical="raw-bytes")])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertNotIn("UNREADABLE", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_all_unreadable_run_is_a_loud_failure(self):
        p = run([receipt("r-1", canonical="nfc-text")])
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("diagnostic: every checked receipt is UNREADABLE or UNFETCHED", p.stderr)
        self.assertIn("this run read no source and is not a pass", p.stdout)
        self.assertEqual(p.returncode, 1)


class Gap2LineRangeHashing(unittest.TestCase):
    def test_lines_hash_joined_with_newline_no_trailing_newline(self):
        p = run([receipt("r-1", lines="2-3", form_used="lines-utf8-nl",
                         sha256=sha(b"line two\nline three"))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("raw.txt lines 2-3", p.stdout)
        self.assertIn("form_used=lines-utf8-nl", p.stdout)

    def test_trailing_newline_is_not_part_of_the_region(self):
        p = run([receipt("r-1", lines="2-3", form_used="lines-utf8-nl",
                         sha256=sha(b"line two\nline three\n"))])
        self.assertIn("[CHANGED] r-1", p.stdout)

    def test_line_range_without_named_form_is_unreadable(self):
        p = run([receipt("r-1", lines="2-3", sha256=sha(b"line two\nline three"))])
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("undeclared form", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_canonical_may_supply_form_used_when_not_raw_bytes(self):
        p = run([receipt("r-1", lines="2-3", canonical="lines-utf8-nl",
                         sha256=sha(b"line two\nline three"))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("form_used=lines-utf8-nl", p.stdout)

    def test_hash_matching_only_under_another_form_is_unreadable(self):
        # Named raw-bytes (whole file) but sha256 is the line-range digest.
        p = run([receipt("r-1", lines="2-3", form_used="raw-bytes",
                         sha256=sha(b"line two\nline three"))])
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("matches under 'lines-utf8-nl'", p.stdout)
        self.assertIn("wrong-form match is not OK", p.stdout)
        self.assertNotIn("[CHANGED]", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_whole_file_ok_surfaces_form_used_raw_bytes(self):
        p = run([receipt("r-1", sha256=sha(RAW))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("form_used=raw-bytes", p.stdout)

    # Kama #forge 2026-10-10: a line holding byte ff, hashed, then ff -> fe,
    # still read OK under replacement. Invalid UTF-8 in the range is
    # UNREADABLE, naming the form; never replaced.
    FF = b"line one\nbad \xff here\nline three\n"
    FE = b"line one\nbad \xfe here\nline three\n"
    REPLACED = sha("bad \ufffd here".encode("utf-8"))

    def test_kama_ff_to_fe_is_unreadable_not_ok(self):
        p = run([receipt("r-1", lines="2", form_used="lines-utf8-nl", sha256=self.REPLACED)],
                raw=self.FE)
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("invalid UTF-8 at line 2", p.stdout)
        self.assertIn("'lines-utf8-nl'", p.stdout)
        self.assertIn("never replaced", p.stdout)
        self.assertNotIn("[  OK   ]", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_kama_original_ff_is_unreadable_too(self):
        for digest in (self.REPLACED, sha(b"bad \xff here")):
            p = run([receipt("r-1", lines="2", form_used="lines-utf8-nl", sha256=digest)],
                    raw=self.FF)
            self.assertIn("[UNREADABLE] r-1", p.stdout)
            self.assertIn("'lines-utf8-nl'", p.stdout)
            self.assertNotIn("[  OK   ]", p.stdout)

    def test_invalid_range_is_unreadable_even_without_sha256(self):
        p = run([receipt("r-1", lines="1-3", form_used="lines-utf8-nl")], raw=self.FF)
        self.assertIn("[UNREADABLE] r-1", p.stdout)

    def test_other_form_match_cannot_turn_invalid_range_into_ok(self):
        # sha256 is the whole file's raw bytes; named form is lines-utf8-nl.
        p = run([receipt("r-1", lines="1-3", form_used="lines-utf8-nl", sha256=sha(self.FF))],
                raw=self.FF)
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("invalid UTF-8", p.stdout)
        self.assertNotIn("[  OK   ]", p.stdout)

    # Kama #forge 2026-10-10: split on 0a only. Lume #forge 2026-10-11:
    # str.splitlines also breaks on 0b, 1c, 1d, 1e; keep the trailing 0d.
    def test_only_0a_is_a_line_boundary(self):
        raw = b"one\x0btwo\x1cthree\x1dfour\x1efive\x0csix\rseven\nlast\n"
        p = run([receipt("r-1", lines="2", form_used="lines-utf8-nl", sha256=sha(b"last"))],
                raw=raw)
        self.assertIn("[  OK   ] r-1", p.stdout)
        p = run([receipt("r-1", lines="1", form_used="lines-utf8-nl",
                         sha256=sha(raw.split(b"\n")[0]))], raw=raw)
        self.assertIn("[  OK   ] r-1", p.stdout)

    def test_crlf_to_lf_reads_changed(self):
        crlf = b"line one\r\nline two\r\nline three\r\n"
        digest = sha(b"line two\r")
        p = run([receipt("r-1", lines="2", form_used="lines-utf8-nl", sha256=digest)], raw=crlf)
        self.assertIn("[  OK   ] r-1", p.stdout)
        p = run([receipt("r-1", lines="2", form_used="lines-utf8-nl", sha256=digest)],
                raw=crlf.replace(b"\r\n", b"\n"))
        self.assertIn("[CHANGED] r-1", p.stdout)

    def test_final_newline_does_not_add_an_empty_line(self):
        p = run([receipt("r-1", lines="3-4", form_used="lines-utf8-nl",
                         sha256=sha(b"line three\n"))], raw=b"a\nb\nline three\n")
        self.assertNotIn("[  OK   ] r-1", p.stdout)

    def test_invalid_bytes_outside_the_range_do_not_matter(self):
        p = run([receipt("r-1", lines="3", form_used="lines-utf8-nl", sha256=sha(b"line three"))],
                raw=self.FF)
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("raw.txt lines 3", p.stdout)


class SidecarReceiptsFile(unittest.TestCase):
    """Kama receipts-file + JSON-strictness cuts; Lume BOM / empty-middle (#forge)."""

    def _line(self):
        return (json.dumps(receipt("r-1", sha256=sha(RAW))) + "\n").encode("utf-8")

    def test_normal_sidecar_still_ok(self):
        p = run([receipt("r-1", sha256=sha(RAW))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_leading_bom_errors_on_line_1(self):
        # ef bb bf decodes to U+FEFF; json.loads rejects; bytes are witnessed.
        body = b"\xef\xbb\xbf" + self._line()
        p = run(body)
        self.assertIn("error: line 1 is not valid JSON", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_empty_middle_line_errors_by_line(self):
        line = self._line().rstrip(b"\n")
        body = line + b"\n\n" + line + b"\n"
        p = run(body)
        self.assertIn("error: line 2 is empty", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_final_0a_does_not_start_an_empty_line(self):
        p = run(self._line())  # ends with 0a
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_invalid_utf8_in_sidecar_names_the_line(self):
        line = self._line().rstrip(b"\n")
        body = line + b"\n" + b"bad \xff line\n"
        p = run(body)
        self.assertIn("error: line 2 is not valid UTF-8", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_duplicate_keys_error_names_line_and_key(self):
        # Bytes carry two claims; lenient json.loads kept the last with no warning.
        line = (
            b'{"id":"r-1","claim":"x","claim":"y","author":"a@example.test",'
            b'"date":"2026-09-01","source":{"uri":"raw.txt","sha256":"'
            + sha(RAW).encode()
            + b'"}}\n'
        )
        p = run(line)
        self.assertIn("error: line 1 has duplicate key 'claim'", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_nan_is_not_json_error_names_line(self):
        line = (
            b'{"id":"r-1","claim":NaN,"author":"a@example.test","date":"2026-09-01",'
            b'"source":{"uri":"raw.txt"}}\n'
        )
        p = run(line)
        self.assertIn("error: line 1 is not valid JSON", p.stderr)
        self.assertIn("NaN", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_infinity_is_not_json_error_names_line(self):
        line = (
            b'{"id":"r-1","claim":Infinity,"author":"a@example.test","date":"2026-09-01",'
            b'"source":{"uri":"raw.txt"}}\n'
        )
        p = run(line)
        self.assertIn("error: line 1 is not valid JSON", p.stderr)
        self.assertIn("Infinity", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_non_object_json_errors_before_fields(self):
        # Substring field check used to pass, then TypeError on r["source"].
        p = run(b'"id claim source author date"\n')
        self.assertIn("error: line 1 is JSON but not an object", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_json_array_is_not_an_object(self):
        p = run(b'[{"id":"r-1"}]\n')
        self.assertIn("error: line 1 is JSON but not an object", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    # Kama #forge 2026-10-15: a line of 200,000 '[' was a RecursionError traceback.
    def test_200000_brackets_name_the_line(self):
        p = run(self._line() + b"[" * 200_000 + b"\n")
        self.assertIn("error: line 2 is nested deeper than 64 (§4)", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotIn("RecursionError", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_deep_value_inside_a_receipt_names_the_line(self):
        deep = b"[" * 200_000 + b"]" * 200_000
        line = b'{"id":"r-1","claim":"x","author":"a","date":"2026-09-01","source":{"uri":"raw.txt"},"x":' + deep + b"}\n"
        p = run(line)
        self.assertIn("error: line 1 is nested deeper", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_deep_objects_name_the_line(self):
        p = run(b'{"a":' * 200_000 + b"\n")
        self.assertIn("error: line 1 is nested deeper", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


class CoreFieldTypes(unittest.TestCase):
    """Kama #forge 2026-10-16: presence was checked, type wasn't (§4.1)."""

    def test_id_list_names_line_and_field_not_a_traceback(self):
        p = run([{**receipt("r-1"), "id": ["a"]}])  # was TypeError: unhashable
        self.assertIn("error: receipt on line 1 field 'id' is an array, not a string", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_id_1_and_id_string_1_are_not_two_ids(self):
        # Both passed as unique and printed as 1.
        p = run([{**receipt("r-1", sha256=sha(RAW)), "id": 1},
                 {**receipt("r-2", sha256=sha(RAW)), "id": "1"}])
        self.assertIn("error: receipt on line 1 field 'id' is a number, not a string", p.stderr)
        self.assertNotIn("[  OK   ]", p.stdout)
        self.assertNotEqual(p.returncode, 0)

    def test_claim_null(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "claim": None}])
        self.assertIn("error: receipt on line 1 field 'claim' is null, not a string", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_author_42(self):
        p = run([receipt("r-1", sha256=sha(RAW)), {**receipt("r-2", sha256=sha(RAW)), "author": 42}])
        self.assertIn("error: receipt on line 2 field 'author' is a number, not a string", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_date_yesterday(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "date": "yesterday"}])
        self.assertIn("error: receipt on line 1 field 'date' is 'yesterday', not a YYYY-MM-DD date",
                      p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_date_not_a_string(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "date": 20260901}])
        self.assertIn("error: receipt on line 1 field 'date' is a number, not a YYYY-MM-DD date", p.stderr)

    def test_supersedes_not_a_string_names_the_line(self):
        p = run([receipt("r-1"), {**receipt("r-2"), "supersedes": ["r-1"]}])
        self.assertIn("error: receipt on line 2 field 'supersedes' is an array, not a string or null",
                      p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_well_typed_receipt_still_ok(self):
        p = run([receipt("r-1", sha256=sha(RAW))], "--strict")
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)


def nested(depth):
    """A receipt line whose deepest array or object is at `depth` (§4 count:
    the top-level object is depth 1, so `depth - 1` arrays sit inside it)."""
    inner = "[" * (depth - 1) + "]" * (depth - 1)
    body = json.dumps(receipt("r-1", sha256=sha(RAW)))
    return (body[:-1] + ', "x": ' + (inner or "0") + "}\n").encode("utf-8")


class DepthLimit(unittest.TestCase):
    """Kama #forge 2026-10-18: deeper than 64 is an error naming the line, and
    every checker agrees. Counted by the §4 rule, not the parser's limit."""

    def test_depth_64_is_read(self):
        p = run(nested(64))
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_depth_65_names_the_line(self):
        # At 90db1d0 this read OK: CPython's parser goes far past 65.
        p = run(json.dumps(receipt("r-0")).encode() + b"\n" + nested(65))
        self.assertIn("error: line 2 is nested deeper than 64 (§4)", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_objects_count_like_arrays(self):
        deep = '{"a":' * 64 + "0" + "}" * 64  # 64 objects inside the top-level one: depth 65
        body = json.dumps(receipt("r-1"))
        p = run((body[:-1] + ', "x": ' + deep + "}\n").encode())
        self.assertIn("error: line 1 is nested deeper than 64 (§4)", p.stderr)

    def test_brackets_inside_strings_do_not_count(self):
        claim = '[{\\"' * 100  # brackets and an escaped quote, all inside one string
        r = {**receipt("r-1", sha256=sha(RAW)), "claim": json.loads('"' + claim + '"')}
        p = run([r])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)


class CoreStringsNameSomething(unittest.TestCase):
    """Kama #forge 2026-10-18: "" as a string is cut. id, claim and author are
    non-empty and not only whitespace, else an error naming line and field."""

    def assertNamed(self, p, line, field, what):
        self.assertIn(f"error: receipt on line {line} field '{field}' is {what}", p.stderr)
        self.assertNotIn("[  OK   ]", p.stdout)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_author_empty(self):  # Kama: checked OK, exit 0
        p = run([{**receipt("r-1", sha256=sha(RAW)), "author": ""}])
        self.assertNamed(p, 1, "author", "empty")

    def test_author_two_spaces(self):  # Kama: checked OK, exit 0
        p = run([receipt("r-1", sha256=sha(RAW)), {**receipt("r-2", sha256=sha(RAW)), "author": "  "}])
        self.assertNamed(p, 2, "author", "only whitespace ('  ')")

    def test_id_empty(self):  # Kama: checked OK, exit 0
        p = run([{**receipt("r-1", sha256=sha(RAW)), "id": ""}])
        self.assertNamed(p, 1, "id", "empty")

    def test_claim_only_whitespace(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "claim": "\t\r\n"}])
        self.assertNamed(p, 1, "claim", "only whitespace")

    def test_unicode_white_space_counts(self):
        # U+3000 and U+00A0 are Unicode White_Space (§4.1 list).
        p = run([{**receipt("r-1", sha256=sha(RAW)), "author": "\u3000\u00a0"}])
        self.assertNamed(p, 1, "author", "only whitespace")


class ControlCharacters(unittest.TestCase):
    """Kama #forge 2026-10-19: a C0 control (U+0000-U+001F) in id, claim or
    author is an error naming line and field. DEL (U+007F) too: @grok draft.
    At fb0828a author "a\\u0000b", an id with 1b, and claim "a\\tb" checked OK."""

    def assertNamed(self, p, line, field, what):
        self.assertIn(f"error: receipt on line {line} field '{field}' {what}", p.stderr)
        self.assertNotIn("[  OK   ]", p.stdout)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_nul_in_author(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "author": "a\x00b"}])
        self.assertNamed(p, 1, "author", "contains control character U+0000 at index 1")

    def test_escape_in_id_on_line_2(self):
        p = run([receipt("r-1", sha256=sha(RAW)), {**receipt("r-2", sha256=sha(RAW)), "id": "r\x1b2"}])
        self.assertNamed(p, 2, "id", "contains control character U+001B at index 1")

    def test_tab_and_newline_in_claim(self):  # C0 includes 09, 0a, 0d
        for ch in "\t\n\r":
            with self.subTest(ch=hex(ord(ch))):
                p = run([{**receipt("r-1", sha256=sha(RAW)), "claim": "a" + ch + "b"}])
                self.assertNamed(p, 1, "claim", f"contains control character U+{ord(ch):04X} at index 1")

    def test_every_c0_and_del(self):
        for cp in [*range(0x20), 0x7F]:
            with self.subTest(cp=hex(cp)):
                p = run([{**receipt("r-1", sha256=sha(RAW)), "author": "x" + chr(cp)}])
                self.assertNamed(p, 1, "author", f"contains control character U+{cp:04X}")

    def test_c1_and_printable_neighbours_still_pass(self):  # C1 is not cut
        for value in ("x\x80y", "x\x85y", "x\x9fy", "a b", "x~y"):
            with self.subTest(value=value):
                p = run([{**receipt("r-1", sha256=sha(RAW)), "author": value}])
                self.assertIn("[  OK   ] r-1", p.stdout)
                self.assertEqual(p.returncode, 0)

    def test_only_whitespace_is_still_named_as_such(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "claim": "\t\r\n"}])
        self.assertNamed(p, 1, "claim", "is only whitespace")


class SourceAndKindTypes(unittest.TestCase):
    """Kama #forge 2026-10-18 type cut: sha256 42 and kind ["read"] were
    TypeError tracebacks; lines "abc" read UNREADABLE. Each is now an error
    naming the line and the field, before any source is read (§4.1)."""

    def assertNamed(self, p, field, what, line=1):
        self.assertIn(f"error: receipt on line {line} field '{field}' is {what}", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotIn("[", p.stdout)  # no verdict printed
        self.assertNotEqual(p.returncode, 0)

    def test_sha256_42(self):
        p = run([receipt("r-1", sha256=42)])
        self.assertNamed(p, "source.sha256", "a number, not 64 lowercase hex digits")

    def test_sha256_empty_is_not_absent(self):  # was OK, read as no hash
        p = run([receipt("r-1", sha256="")])
        self.assertNamed(p, "source.sha256", "'', not 64 lowercase hex digits")

    def test_sha256_uppercase(self):  # was CHANGED: a source that never moved
        p = run([receipt("r-1", sha256=sha(RAW).upper())])
        self.assertNamed(p, "source.sha256", repr(sha(RAW).upper()) + ", not 64 lowercase hex digits")

    def test_sha256_uppercase_names_line_and_field_not_a_mismatch(self):
        # Kama #forge 2026-10-19: lowercase only. Line 2, mixed case, and a
        # source that did change: still the receipt's error, never CHANGED.
        mixed = sha(b"other bytes")[:32] + sha(b"other bytes")[32:].upper()
        p = run([receipt("r-1", sha256=sha(RAW)), receipt("r-2", sha256=mixed)])
        self.assertNamed(p, "source.sha256", repr(mixed) + ", not 64 lowercase hex digits: "
                         "uppercase hex is not folded or compared (lowercase only)", line=2)
        self.assertNotIn("CHANGED", p.stdout + p.stderr)
        self.assertNotIn("mismatch", p.stdout + p.stderr)

    def test_sha256_not_hex_is_not_called_uppercase(self):
        p = run([receipt("r-1", sha256="G" * 64)])
        self.assertNamed(p, "source.sha256", repr("G" * 64) + ", not 64 lowercase hex digits")
        self.assertNotIn("uppercase", p.stderr)

    def test_sha256_null(self):
        p = run([receipt("r-1", sha256=None)])
        self.assertNamed(p, "source.sha256", "null, not 64 lowercase hex digits")

    def test_type_error_comes_before_the_source_is_read(self):  # was MISSING
        p = run([receipt("r-1", uri="nowhere.txt", sha256=42)])
        self.assertNamed(p, "source.sha256", "a number")

    def test_kind_list(self):
        p = run([receipt("r-1"), {**receipt("r-2"), "kind": ["read"]}])
        self.assertNamed(p, "kind", "an array, not a string", line=2)

    def test_kind_string_outside_the_table_still_warns(self):
        p = run([{**receipt("r-1"), "kind": "invoice"}])
        self.assertIn("kind is not one of the §11 classes", p.stderr)
        self.assertNotIn("error:", p.stderr)

    def test_lines_abc(self):  # was UNREADABLE, exit 1
        p = run([receipt("r-1", lines="abc")])
        self.assertNamed(p, "source.lines", "'abc', not A or A-B")

    def test_lines_abc_with_form_used(self):  # was a ValueError traceback
        p = run([receipt("r-1", lines="abc", form_used="lines-utf8-nl")])
        self.assertNamed(p, "source.lines", "'abc', not A or A-B")

    def test_lines_shapes_int_accepts(self):
        # Each was read by int(): "0-1" selected no bytes and read OK;
        # "\u0662" is an Arabic-Indic 2; 2 (a number) was str()-ed to "2".
        for bad, shown in (("0-1", "'0-1'"), ("3-2", "'3-2'"), ("02", "'02'"), (" 2", "' 2'"),
                           ("+2", "'+2'"), ("1_0", "'1_0'"), ("\u0662", repr("\u0662")),
                           ("2-", "'2-'"), (2, "a number"), (["2"], "an array"), (None, "null")):
            with self.subTest(lines=bad):
                p = run([receipt("r-1", lines=bad, form_used="lines-utf8-nl", sha256=sha(b"line two"))])
                self.assertNamed(p, "source.lines", shown + ", not A or A-B")

    def test_good_lines_still_check(self):
        for good, data in (("2", b"line two"), ("2-3", b"line two\nline three"),
                           ("1-1", b"line one")):
            with self.subTest(lines=good):
                p = run([receipt("r-1", lines=good, form_used="lines-utf8-nl", sha256=sha(data))])
                self.assertIn("[  OK   ] r-1", p.stdout)
                self.assertEqual(p.returncode, 0)


class Gap3Span(unittest.TestCase):
    def test_span_is_not_applied_and_says_so(self):
        p = run([receipt("r-1", span="5-12", sha256=sha(RAW))])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("span '5-12' not applied", p.stdout)

    def test_span_note_travels_with_a_mismatch(self):
        p = run([receipt("r-1", span="5-12", sha256=sha(b"line"))])
        self.assertIn("[CHANGED] r-1", p.stdout)
        self.assertIn("not applied", p.stdout)


class Gap4RemoteUris(unittest.TestCase):
    def test_url_is_unfetched_not_missing_or_unreadable(self):
        p = run([receipt("r-1", uri="https://example.test/raw.txt")])
        self.assertIn("[UNFETCHED] r-1", p.stdout)
        self.assertNotIn("[UNREADABLE]", p.stdout)
        self.assertNotIn("MISSING", p.stdout)
        self.assertIn("diagnostic: every checked receipt is UNREADABLE or UNFETCHED", p.stderr)
        self.assertIn("not a pass", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_urn_is_unfetched_not_missing(self):
        p = run([receipt("r-1", uri="urn:example:raw")])
        self.assertIn("[UNFETCHED] r-1", p.stdout)
        self.assertNotIn("[UNREADABLE]", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_ok_beside_unfetched_is_not_the_all_unreadable_diagnostic(self):
        p = run([receipt("r-1", sha256=sha(RAW)), receipt("r-2", uri="https://example.test/raw.txt")])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("[UNFETCHED] r-2", p.stdout)
        self.assertNotIn("diagnostic:", p.stderr)
        self.assertEqual(p.returncode, 1)

    def test_mixed_unreadable_and_unfetched_is_a_loud_failure(self):
        p = run([receipt("r-1", sha256=sha(RAW), canonical="nfc-text"),
                 receipt("r-2", uri="urn:example:raw")])
        self.assertIn("[UNREADABLE] r-1", p.stdout)
        self.assertIn("[UNFETCHED] r-2", p.stdout)
        self.assertIn("diagnostic: every checked receipt is UNREADABLE or UNFETCHED", p.stderr)
        self.assertNotEqual(p.returncode, 0)


class Gap5SourceUri(unittest.TestCase):
    def test_missing_uri_is_a_schema_error(self):
        r = receipt("r-1")
        del r["source"]["uri"]
        p = run([r])
        self.assertIn("missing required field 'source.uri'", p.stderr)
        self.assertNotIn("MISSING", p.stdout)
        self.assertNotEqual(p.returncode, 0)


class Gap6IdsAndSupersedes(unittest.TestCase):
    def test_duplicate_ids_are_an_error(self):
        p = run([receipt("r-1"), receipt("r-1")])
        self.assertIn("reuses id 'r-1' from line 1", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_supersedes_resolves_chains_in_file_order(self):
        p = run([receipt("r-1"), receipt("r-2", "r-1"), receipt("r-3", "r-2")])
        self.assertIn("3 receipts, 2 superseded, sampling 1", p.stdout)
        self.assertIn("] r-3:", p.stdout)
        self.assertEqual(p.stderr, "")

    def test_supersedes_pointing_later_is_ignored_and_flagged(self):
        p = run([receipt("r-1", "r-2"), receipt("r-2")])
        self.assertIn("r-1 supersedes r-2, which comes later in the file; ignored", p.stderr)
        self.assertIn("0 superseded", p.stdout)

    def test_dangling_supersedes_is_flagged(self):
        p = run([receipt("r-1", "r-9")])
        self.assertIn("warning: r-1 supersedes r-9, which is not in this file", p.stderr)
        self.assertEqual(p.returncode, 0)

    def test_dangling_supersedes_is_an_error_under_strict(self):
        p = run([receipt("r-1", "r-9")], "--strict")
        self.assertIn("error: r-1 supersedes r-9", p.stderr)
        self.assertNotEqual(p.returncode, 0)


class SupersedeForks(unittest.TestCase):
    """Kama #forge 2026-10-17: two receipts superseding one id are named, not resolved."""

    def fork(self, *extra):
        a = {**receipt("a", sha256=sha(RAW)), "claim": "x is 1"}
        b = {**receipt("b", "a", sha256=sha(RAW)), "claim": "x is 2"}
        c = {**receipt("c", "a", sha256=sha(RAW)), "claim": "x is 3"}
        return [a, b, c, *extra]

    def test_kama_a_b_c_is_forked_both_current(self):
        p = run(self.fork())
        line = "FORKED: a (line 1) is superseded by b (line 2) and c (line 3); both stay current"
        self.assertIn("  [FORKED] a (line 1) is superseded by b (line 2) and c (line 3)", p.stdout)
        self.assertIn("warning: " + line, p.stderr)
        self.assertIn("3 receipts, 1 superseded, sampling 2", p.stdout)
        self.assertIn("[  OK   ] b: x is 2", p.stdout)
        self.assertIn("[  OK   ] c: x is 3", p.stdout)
        self.assertNotIn("] a:", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_kama_a_b_c_is_an_error_under_strict(self):
        p = run(self.fork(), "--strict")
        self.assertIn("error: FORKED: a (line 1) is superseded by b (line 2) and c (line 3)", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_superseding_the_other_correction_makes_a_chain(self):
        d = {**receipt("d", "c", sha256=sha(RAW)), "claim": "c withdrawn; x is 2"}
        p = run(self.fork(d), "--strict")
        self.assertNotIn("FORKED", p.stdout + p.stderr)
        self.assertIn("4 receipts, 2 superseded, sampling 2", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_three_way_fork_names_every_line(self):
        e = {**receipt("e", "a", sha256=sha(RAW)), "claim": "x is 4"}
        p = run(self.fork(e))
        self.assertIn("by b (line 2) and c (line 3) and e (line 4); all stay current", p.stdout)

    def test_single_correction_is_not_a_fork(self):
        p = run(self.fork()[:2], "--strict")
        self.assertNotIn("FORKED", p.stdout + p.stderr)
        self.assertEqual(p.returncode, 0)


class Gap7Sampling(unittest.TestCase):
    RECEIPTS = [receipt(f"r-{i}") for i in range(10)]

    def test_seed_and_method_are_printed(self):
        p = run(self.RECEIPTS, "--sample", "3", "--seed", "42")
        self.assertIn("sample: random.Random(42).sample of 3 from 10 current receipts", p.stdout)
        self.assertIn("from: sidecar sha256 ", p.stdout)
        self.assertIn("checked: 2026-09-27", p.stdout)

    def test_unseeded_sample_prints_a_seed_that_reproduces_it(self):
        first = run(self.RECEIPTS, "--sample", "3")
        seed = first.stdout.split("random.Random(")[1].split(")")[0]
        again = run(self.RECEIPTS, "--sample", "3", "--seed", seed)
        self.assertEqual(first.stdout, again.stdout)

    def test_full_check_says_no_random_draw(self):
        p = run(self.RECEIPTS)
        self.assertIn("sample: all 10 current receipts, no random draw", p.stdout)


class Gap8ReviewBy(unittest.TestCase):
    def reviewed(self, review_by, **kw):
        return {**receipt("r-1", **kw), "review_by": review_by, "review_conditions": "rerun count"}

    def test_past_review_by_is_stale_and_fails(self):
        p = run([self.reviewed("2026-09-26")])
        self.assertIn("[ STALE ] r-1: review_by 2026-09-26 has passed as of 2026-09-27", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_review_by_today_is_not_stale(self):
        p = run([self.reviewed("2026-09-27")])
        self.assertNotIn("STALE", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_today_flag_makes_runs_reproducible(self):
        p = run([self.reviewed("2026-10-01")], "--today", "2026-10-02")
        self.assertIn("STALE", p.stdout)

    def test_superseded_receipt_is_not_stale(self):
        p = run([self.reviewed("2026-09-01"), receipt("r-2", "r-1")], "--all")
        self.assertNotIn("STALE", p.stdout)

    def test_bad_review_by_is_an_error(self):
        p = run([self.reviewed("soon")])
        self.assertIn("not a YYYY-MM-DD date", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_review_by_without_conditions_warns(self):
        r = {**receipt("r-1"), "review_by": "2026-12-01"}
        p = run([r])
        self.assertIn("review_by has no review_conditions beside it (§7)", p.stderr)


class Gap9DerivedMarks(unittest.TestCase):
    def read(self, **kw):
        return {**receipt("r-1"), "kind": "read", "subject": "s", "authorizer": "a",
                "reader": "r", "window": "2026-09-01/2026-09-30", **kw}

    def test_unwitnessed_when_witness_absent(self):
        p = run([self.read()])
        self.assertIn("[UNWITNESSED] r-1: read has no witness", p.stdout)
        self.assertIn("no party_registry bound; transitional string-compare", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_authorizer_cannot_be_witness(self):
        p = run([self.read(witness="a")])
        self.assertIn("the authorizer cannot be the witness", p.stdout)

    def test_distinct_witness_is_not_marked_but_window_is_noted(self):
        p = run([self.read(witness="w-hand")])
        self.assertNotIn("UNWITNESSED", p.stdout)
        self.assertIn("witness window not checked", p.stdout)
        self.assertIn("no party_registry bound; transitional string-compare", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_subject_who_authorized_needs_no_witness(self):
        p = run([self.read(subject="a")])
        self.assertNotIn("UNWITNESSED", p.stdout)

    def test_report_says_what_it_implements(self):
        p = run([receipt("r-1")])
        self.assertIn("SPEC v0.2-draft subset", p.stdout)


class RegistryBoundWitness(unittest.TestCase):
    """Kama #forge narrowing: witness must resolve in party_registry (§11.3)."""

    def read(self, **kw):
        return {**receipt("r-1"), "kind": "read", "subject": "s", "authorizer": "a",
                "reader": "r", "window": "2026-09-01/2026-09-30",
                "party_registry": "guests.txt", **kw}

    def run_with_registry(self, receipts, guests, *args):
        import tempfile, subprocess, sys, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "raw.txt").write_bytes(RAW)
            (Path(d) / "guests.txt").write_text(guests)
            sidecar = Path(d) / "report.md.receipts.jsonl"
            sidecar.write_text("".join(json.dumps(r) + "\n" for r in receipts))
            return subprocess.run(
                [sys.executable, str(CHECK), str(sidecar), "--today", "2026-09-27", *args],
                capture_output=True, text=True)

    def test_witness_in_registry_is_not_unwitnessed(self):
        p = self.run_with_registry(
            [self.read(witness="w-hand")],
            "# guest list\ns\na\nr\nw-hand\n")
        self.assertNotIn("UNWITNESSED", p.stdout)
        self.assertIn("witness window not checked", p.stdout)
        self.assertNotIn("transitional string-compare", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_witness_missing_from_registry_is_unwitnessed(self):
        p = self.run_with_registry(
            [self.read(witness="stranger")],
            "s\na\nr\nw-hand\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("does not resolve in party_registry", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_unreadable_registry_is_unwitnessed(self):
        p = run([self.read(witness="w-hand", party_registry="missing-guests.txt")])
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("cannot be read", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_other_slot_not_in_registry_is_noted_not_a_clear(self):
        p = self.run_with_registry(
            [self.read(witness="w-hand", subject="not-on-list")],
            "a\nr\nw-hand\n")
        self.assertNotIn("[UNWITNESSED]", p.stdout)
        self.assertIn("subject 'not-on-list' not in party_registry", p.stdout)
        self.assertEqual(p.returncode, 0)


class RegistryReadStrictly(unittest.TestCase):
    """Kama registry cut (#forge 2026-10-12): party_registry is read as the
    sidecar is — bytes, 0a only, strict UTF-8, BOM an error, by line."""

    def check(self, guests: bytes, witness="w-hand"):
        r = {**receipt("r-1"), "kind": "read", "subject": "s", "authorizer": "a",
             "reader": "r", "window": "2026-09-01/2026-09-30",
             "party_registry": "guests.txt", "witness": witness}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "raw.txt").write_bytes(RAW)
            (Path(d) / "guests.txt").write_bytes(guests)
            sidecar = Path(d) / "report.md.receipts.jsonl"
            sidecar.write_text(json.dumps(r) + "\n")
            return subprocess.run([sys.executable, str(CHECK), str(sidecar), "--today", "2026-09-27"],
                                  capture_output=True, text=True)

    def test_clean_registry_resolves(self):
        p = self.check(b"# guests\ns\n\na\nr\nw-hand")  # comment, empty line, no final 0a
        self.assertNotIn("UNWITNESSED", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_invalid_utf8_names_the_registry_line(self):
        # errors="replace" read this clean: w-hand on line 3 still resolved.
        p = self.check(b"a\nbad \xff\nw-hand\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("party_registry 'guests.txt' line 2 is not valid UTF-8", p.stdout)
        self.assertIn("cannot be read", p.stdout)
        self.assertNotIn("Traceback", p.stderr)
        self.assertEqual(p.returncode, 1)

    def test_leading_bom_errors_on_line_1(self):
        # The BOM rode along on the comment line, so w-hand resolved before.
        p = self.check(b"\xef\xbb\xbf# guests\nw-hand\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("line 1 starts with a UTF-8 BOM", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_lone_0d_is_not_a_line_boundary(self):
        # str.splitlines split this into four ids, so w-hand resolved before.
        p = self.check(b"s\ra\rr\rw-hand\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("witness 'w-hand' does not resolve in party_registry", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_trailing_0d_stays_in_its_line_and_names_it(self):
        p = self.check(b"a\r\nw-hand\r\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("line 1 begins or ends with whitespace ('a\\r')", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_edge_whitespace_is_not_stripped(self):
        p = self.check(b"a\n w-hand\n")
        self.assertIn("line 2 begins or ends with whitespace (' w-hand')", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_crlf_registry_fails_whole(self):
        # Kama #forge 2026-10-18: taken. The first identifier line (2; the
        # comment is skipped) ends in 0d, so no line resolves, w-hand included.
        p = self.check(b"# guests\r\ns\r\na\r\nr\r\nw-hand\r\n")
        self.assertIn("[UNWITNESSED] r-1", p.stdout)
        self.assertIn("line 2 begins or ends with whitespace ('s\\r')", p.stdout)
        self.assertIn("so the registry cannot be read", p.stdout)
        self.assertEqual(p.returncode, 1)


class OneWhitespaceSet(unittest.TestCase):
    """Kama #forge 2026-10-19: one set, not two. At fb0828a 1c-1f were
    whitespace to str.isspace (the registry edge rule) but not to Unicode
    White_Space (id, claim, author): a registry line ending in 1f failed the
    whole registry while an author of only 1f passed. Both now use §4.1."""

    check = RegistryReadStrictly.check

    def test_1f_at_registry_edge_and_1f_only_author_agree(self):
        # Registry: a line ending in 1f is not edge whitespace; it is an id.
        p = self.check(b"s\na\nr\nw-hand\x1f\n", witness="w-hand\x1f")
        self.assertNotIn("begins or ends with whitespace", p.stdout)
        self.assertNotIn("cannot be read", p.stdout)
        self.assertNotIn("UNWITNESSED", p.stdout)
        # Author: only 1f is not "only whitespace" either. Same answer. (It
        # is a C0 control, which id/claim/author refuse: ControlCharacters.)
        p = run([{**receipt("r-1", sha256=sha(RAW)), "author": "\x1f"}])
        self.assertNotIn("only whitespace", p.stderr)
        self.assertIn("field 'author' contains control character U+001F", p.stderr)

    def test_white_space_at_registry_edge_and_white_space_only_author_agree(self):
        # And where the set says yes, both say yes: U+3000 is White_Space.
        p = self.check("a\nw-hand\u3000\n".encode(), witness="w-hand")
        self.assertIn("line 2 begins or ends with whitespace ('w-hand\\u3000')", p.stdout)
        p = run([{**receipt("r-1", sha256=sha(RAW)), "author": "\u3000"}])
        self.assertIn("field 'author' is only whitespace", p.stderr)

    def test_each_1c_to_1f_is_not_registry_edge_whitespace(self):
        for ch in "\x1c\x1d\x1e\x1f":
            with self.subTest(ch=hex(ord(ch))):
                p = self.check(f"s\na\nr\n{ch}w-hand\n".encode(), witness=ch + "w-hand")
                self.assertNotIn("begins or ends with whitespace", p.stdout)
                self.assertNotIn("UNWITNESSED", p.stdout)

    def test_checker_has_one_definition(self):
        # No second whitespace set: no isspace, no bare strip()/split(), no \s.
        import re
        code = [l for l in CHECK.read_text(encoding="utf-8").splitlines()
                if not l.lstrip().startswith("#")]
        for pattern in (r"\.isspace\(", r"\.strip\(\)", r"\.split\(\)", r"\\s"):
            with self.subTest(pattern=pattern):
                self.assertEqual([l for l in code if re.search(pattern, l)], [])


class Gap10NewRequiredFields(unittest.TestCase):
    def test_missing_v02_fields_warn_by_default(self):
        p = run([receipt("r-1", v02=False, sha256=sha(RAW))])
        self.assertIn("warning: r-1 (line 1) lacks v0.2 fields: schema (§4.5)", p.stderr)
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_missing_v02_fields_are_errors_under_strict(self):
        p = run([receipt("r-1", v02=False)], "--strict")
        self.assertIn("error: r-1 (line 1) lacks v0.2 fields", p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertNotEqual(p.returncode, 0)

    def test_complete_receipt_passes_strict(self):
        p = run([receipt("r-1", sha256=sha(RAW))], "--strict")
        self.assertEqual(p.stderr, "")
        self.assertEqual(p.returncode, 0)

    def test_party_needs_did_and_answers_for(self):
        p = run([{**receipt("r-1"), "parties": [{"name": "a"}]}])
        self.assertIn("each party needs 'did' and 'answers_for'", p.stderr)

    def test_continuity_names_which_sameness(self):
        p = run([{**receipt("r-1"), "continuity": "same"}])
        self.assertIn("continuity must be party, process, or both", p.stderr)


class KindAndDispute(unittest.TestCase):
    def test_subject_and_authorizer_without_kind_is_not_a_read(self):
        r = {**receipt("r-1"), "subject": "s", "authorizer": "a", "reader": "r"}
        p = run([r])
        self.assertNotIn("UNWITNESSED", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_unknown_kind_warns(self):
        p = run([{**receipt("r-1"), "kind": "invoice"}])
        self.assertIn("kind is not one of the §11 classes", p.stderr)
        self.assertEqual(p.returncode, 0)

    def test_bad_window_warns_and_strict_fails(self):
        r = {**receipt("r-1"), "kind": "read", "subject": "s", "authorizer": "s", "window": "w"}
        warned = run([r])
        self.assertIn("window must be YYYY-MM-DD/YYYY-MM-DD", warned.stderr)
        self.assertEqual(warned.returncode, 0)
        strict = run([r], "--strict")
        self.assertNotEqual(strict.returncode, 0)

    def test_disputed_annotation_is_reported_not_computed_away(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "disputed": "claim overreaches the log"}])
        self.assertIn("[  OK   ] r-1", p.stdout)
        self.assertIn("[DISPUTED] r-1: human mark, not computed: claim overreaches the log", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_disputed_false_is_not_a_mark(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "disputed": False}])
        self.assertNotIn("DISPUTED", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_sampling_warrant_is_on_the_report(self):
        p = run([receipt("r-1", sha256=sha(RAW))])
        self.assertIn("sampling_warrant: this run licenses nothing about receipts it did not read", p.stdout)


class KindsFromLaterFolds(unittest.TestCase):
    def test_authorization_and_intent_are_classes(self):
        for kind in ("authorization", "intent"):
            p = run([{**receipt("r-1", sha256=sha(RAW)), "kind": kind}], "--strict")
            self.assertEqual(p.stderr, "", kind)
            self.assertEqual(p.returncode, 0, kind)

    def test_intent_kind_computes_no_mark(self):
        p = run([{**receipt("r-1", sha256=sha(RAW)), "kind": "intent"}])
        self.assertNotIn("CLAIMED", p.stdout)
        self.assertNotIn("UNWITNESSED", p.stdout)


DECISIONS = """# DECISIONS

## D-001 · 2026-08-07 · Process

- **Source:** #forge, 2026-08-07, @a
- **Author:** A

## D-002 · 2026-08-08 · A rule

- **Source:** #forge, 2026-08-08 (@a, proposal);
  2026-08-09 (@b, cut)
- **Author:** A

## Open · D-003 · Not yet

- **Source:** #forge, 2026-08-10 (@a)
"""

SPEC = """# spec

## 0. About

Mentions D-009 here, which is outside the fold region.

- **Pin.** event 7: closed set D-001 through D-002.
- **Pin reads.** Who read the quote, when, against which commit.
  - @a, event 8, 2026-08-11: pin 7 read against `abc1234`.

## 1. Rules

- A rule. (D-002 b)

## 12. Open questions

1. D-003 is open.

## Appendix A

### Dropped

- D-001 — process only.

## Appendix B. Fold sources

- **D-001** — #forge, 2026-08-07, @a
- **D-002** — #forge, 2026-08-08 (@a, proposal); 2026-08-09 (@b, cut)
"""


class Coverage(unittest.TestCase):
    """SPEC §0 fold source: closed D-numbers cited or dropped, both ways."""

    def cover(self, spec=SPEC, decisions=DECISIONS, pin="7", at_pin=DECISIONS):
        """With git installed, the fixture's read line is compared against a
        real commit of DECISIONS (an uncompared read isn't counted)."""
        with tempfile.TemporaryDirectory() as d:
            if shutil.which("git"):
                git = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
                subprocess.run(git[:3] + ["init", "-q"], check=True)
                (Path(d) / "DECISIONS.md").write_text(at_pin)
                subprocess.run(git + ["add", "DECISIONS.md"], check=True)
                subprocess.run(git + ["commit", "-q", "--no-gpg-sign", "-m", "d"], check=True)
                sha = subprocess.run(git[:3] + ["rev-parse", "--short", "HEAD"], check=True,
                                     capture_output=True, text=True).stdout.strip()
                spec = spec.replace("abc1234", sha)
            (Path(d) / "SPEC.md").write_text(spec)
            (Path(d) / "DECISIONS.md").write_text(decisions)
            return subprocess.run([sys.executable, str(CHECK), "--coverage",
                                   str(Path(d) / "SPEC.md"), str(Path(d) / "DECISIONS.md")]
                                  + (["--pin", pin] if pin else []),
                                  capture_output=True, text=True)

    def test_repo_spec_covers_repo_decisions(self):
        # Outside a git checkout (a tarball, or no git binary) the pin reads
        # can't be compared, so the run correctly reads UNWITNESSED. That is
        # not this test's question: skip and say why (Kama #forge 2026-10-10).
        why = not_a_checkout(ROOT)
        if why:
            print(f"\nskipped test_repo_spec_covers_repo_decisions: {why}", file=sys.stderr)
            self.skipTest(why)
        p = subprocess.run([sys.executable, str(CHECK), "--coverage",
                            str(ROOT / "SPEC.md"), str(ROOT / "DECISIONS.md"), "--pin", "565"],
                           capture_output=True, text=True)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_complete_fixture_has_no_gap(self):
        p = self.cover()
        self.assertIn("pinned and closed in DECISIONS.md: 2", p.stdout)
        self.assertIn("cited in SPEC §1–§11: 1; dropped: 1", p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_closed_but_neither_cited_nor_dropped_is_missing(self):
        p = self.cover(spec=SPEC.replace("- D-001 — process only.\n", ""))
        self.assertIn("[MISSING] D-001: closed in DECISIONS.md; not cited", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_cited_but_not_closed_is_reported_with_its_line(self):
        p = self.cover(spec=SPEC.replace("(D-002 b)", "(D-002 b, D-003)"))
        self.assertIn("[NOT CLOSED] D-003: cited in SPEC line 13; not closed", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_open_questions_and_section_0_are_not_folds(self):
        p = self.cover()
        self.assertNotIn("D-003", p.stdout)
        self.assertNotIn("D-009", p.stdout)

    def test_dropped_but_not_closed(self):
        p = self.cover(spec=SPEC.replace("- D-001 — process only.", "- D-001 — process only.\n- D-007 — gone."))
        self.assertIn("[NOT CLOSED] D-007: listed as dropped", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_dropped_and_cited_is_both(self):
        p = self.cover(spec=SPEC.replace("(D-002 b)", "(D-002 b; D-001)"))
        self.assertIn("[BOTH] D-001: listed as dropped and also cited", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_fold_source_must_match_decisions(self):
        p = self.cover(spec=SPEC.replace("(@b, cut)", "(@b, close)"))
        self.assertIn("[SOURCE DRIFT] D-002", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_missing_fold_source_line(self):
        p = self.cover(spec=SPEC.replace("- **D-001** — #forge, 2026-08-07, @a\n", ""))
        self.assertIn("[NO SOURCE] D-001: no Appendix B fold-source line", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_no_pin_input_is_unpinned_before_missing(self):
        p = self.cover(spec=SPEC.replace("- D-001 — process only.\n", ""), pin=None)
        self.assertIn("[UNPINNED] no --pin given", p.stdout)
        self.assertNotIn("MISSING", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_spec_citing_another_pin_is_unpinned(self):
        p = self.cover(pin="8")
        self.assertIn("[UNPINNED] SPEC §0 cites pin event 7, run pinned to event 8", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_spec_citing_no_pin_is_unpinned(self):
        p = self.cover(spec=SPEC.replace("- **Pin.** event 7: closed set D-001 through D-002.\n", ""))
        self.assertIn("[UNPINNED] SPEC §0 cites no pin", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_pin_set_not_closed_in_decisions_is_drift(self):
        p = self.cover(spec=SPEC.replace("D-001 through D-002", "D-001 through D-003"))
        self.assertIn("[PIN DRIFT] D-003: in the pin set; not closed", p.stdout)
        self.assertEqual(p.returncode, 1)

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_closed_after_pin_waits_unless_folded(self):
        late = SPEC.replace("D-001 through D-002", "D-001 through D-001")
        early = DECISIONS.replace("## D-002 ·", "## Open · D-002 ·")  # DECISIONS at the pin
        p = self.cover(spec=late.replace("- A rule. (D-002 b)", "- A rule.").replace(
            "- **D-002** — #forge, 2026-08-08 (@a, proposal); 2026-08-09 (@b, cut)\n", ""),
            at_pin=early)
        self.assertIn("closed after the pin (wait for the next fold): D-002", p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        p = self.cover(spec=late, at_pin=early)
        self.assertIn("[AHEAD OF PIN] D-002", p.stdout)
        self.assertNotIn("[NOT CLOSED] D-002", p.stdout)
        self.assertEqual(p.returncode, 1)

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_pin_read_line_is_listed(self):
        p = self.cover()
        self.assertIn("pin reads naming event 7: 1", p.stdout)
        self.assertNotIn("UNWITNESSED", p.stdout)

    def test_receipts_file_required_without_coverage(self):
        p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True)
        self.assertIn("a receipts file is required unless --coverage is given", p.stderr)
        self.assertNotEqual(p.returncode, 0)


READ = "  - @a, event 8, 2026-08-11: pin 7 read against `abc1234`.\n"


class PinReads(unittest.TestCase):
    """SPEC §0 pin reads (Lume #forge 2026-10-06): who read the quote, against which commit."""

    def cover(self, spec=SPEC, at_commit="", env=None):
        """Run --coverage --pin 7. at_commit: DECISIONS.md text to commit first;
        its sha replaces abc1234 in the read line. Default: commit DECISIONS
        when git is installed, so reads are compared; None: no commit."""
        if at_commit == "":
            at_commit = DECISIONS if shutil.which("git") else None
        with tempfile.TemporaryDirectory() as d:
            dec = Path(d) / "DECISIONS.md"
            if at_commit is not None:
                git = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
                subprocess.run(git[:3] + ["init", "-q"], check=True)
                dec.write_text(at_commit)
                subprocess.run(git + ["add", "DECISIONS.md"], check=True)
                subprocess.run(git + ["commit", "-q", "--no-gpg-sign", "-m", "d"], check=True)
                sha = subprocess.run(git[:3] + ["rev-parse", "--short", "HEAD"], check=True,
                                     capture_output=True, text=True).stdout.strip()
                spec = spec.replace("abc1234", sha)
            dec.write_text(DECISIONS)
            (Path(d) / "SPEC.md").write_text(spec)
            return subprocess.run([sys.executable, str(CHECK), "--coverage", str(Path(d) / "SPEC.md"),
                                   str(dec), "--pin", "7"], capture_output=True, text=True, env=env)

    def test_no_read_line_is_unwitnessed(self):
        p = self.cover(spec=SPEC.replace(READ, ""))
        self.assertIn("[UNWITNESSED] pin quote: no SPEC §0 pin-read line names event 7", p.stdout)
        self.assertIn("coverage: 1 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_read_line_for_another_pin_is_unwitnessed(self):
        p = self.cover(spec=SPEC.replace("pin 7 read", "pin 6 read"))
        self.assertIn("[UNWITNESSED] pin quote", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_unpinned_is_asked_before_unwitnessed(self):
        p = self.cover(spec=SPEC.replace(READ, "").replace("event 7:", "event 6:"))
        self.assertIn("[UNPINNED]", p.stdout)
        self.assertNotIn("UNWITNESSED", p.stdout)
        self.assertEqual(p.returncode, 1)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_read_line_verified_at_its_commit_passes(self):
        p = self.cover(at_commit=DECISIONS)
        self.assertIn("2 closed headings, equal to the quote", p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_commit_set_mismatch_is_pin_read_drift(self):
        p = self.cover(at_commit=DECISIONS.replace("## D-002 ·", "## Open · D-002 ·"))
        self.assertIn("[PIN READ DRIFT] pin quote: @a (event 8) read against", p.stdout)
        self.assertIn("quoted, not closed there: D-002", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_unknown_commit_is_not_compared_not_counted(self):
        # Kama #forge 2026-10-09: a read that wasn't compared isn't counted as compared.
        p = self.cover(at_commit=None)
        self.assertIn("[NOT COMPARED, not counted] against abc1234: skipped", p.stdout)
        self.assertIn("0 counted; 0 AUTHOR, 0 CLAIMED, 1 NOT COMPARED, not counted", p.stdout)
        self.assertIn("[UNWITNESSED] pin quote: no counted", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_git_unavailable_is_not_compared_not_counted(self):
        with tempfile.TemporaryDirectory() as empty:
            p = self.cover(at_commit=None, env={**os.environ, "PATH": empty})
        self.assertIn("[NOT COMPARED, not counted] against abc1234: skipped, git not available",
                      p.stdout)
        self.assertIn("coverage: 1 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_author_and_claimed_skips_keep_their_kind(self):
        p = self.cover(spec=SPEC.replace(READ, READ + AUTHOR_READ + CLAIMED_READ), at_commit=None)
        self.assertIn("[AUTHOR, not counted] against abc1234: skipped", p.stdout)
        self.assertIn("[CLAIMED, not counted] against abc1234: skipped", p.stdout)
        self.assertIn("1 AUTHOR, 1 CLAIMED, 1 NOT COMPARED", p.stdout)


AUTHOR_READ = "  - @b, event 7, 2026-08-10: pin 7 read against `abc1234`. AUTHOR.\n"
CLAIMED_READ = "  - @c, 2026-08-12: pin 7 read against `abc1234`.\n"


class CountedReads(unittest.TestCase):
    """Counted pin reads (Kama, Lume #forge 2026-10-07): a line names the
    reader's own post; AUTHOR and CLAIMED lines are printed, not counted."""

    cover = PinReads.cover

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_author_line_is_reported_not_counted(self):
        p = self.cover(spec=SPEC.replace(READ, READ + AUTHOR_READ))
        self.assertIn("pin reads naming event 7: 1 counted (8); 1 AUTHOR, 0 CLAIMED", p.stdout)
        self.assertIn("pin read @b (event 7, 2026-08-10) [AUTHOR, not counted] against",
                      p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_only_author_line_is_unwitnessed(self):
        p = self.cover(spec=SPEC.replace(READ, AUTHOR_READ))
        self.assertIn("pin reads naming event 7: 0 counted; 1 AUTHOR", p.stdout)
        self.assertIn("[UNWITNESSED] pin quote: no counted SPEC §0 pin-read line names event 7",
                      p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_line_citing_the_pin_post_is_author_unmarked(self):
        p = self.cover(spec=SPEC.replace(READ, AUTHOR_READ.replace(" AUTHOR.", "")))
        self.assertIn("[AUTHOR, not counted]", p.stdout)
        self.assertIn("[UNWITNESSED] pin quote", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_line_by_the_named_pin_author_is_author(self):
        spec = SPEC.replace("event 7: closed", "event 7 (@a, 2026-08-10): closed")
        p = self.cover(spec=spec)
        self.assertIn("pin read @a (event 8, 2026-08-11) [AUTHOR, not counted]", p.stdout)
        self.assertIn("[UNWITNESSED] pin quote", p.stdout)
        self.assertEqual(p.returncode, 1)

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_line_with_no_own_post_is_claimed_not_counted(self):
        p = self.cover(spec=SPEC.replace(READ, READ + CLAIMED_READ))
        self.assertIn("1 counted (8); 0 AUTHOR, 1 CLAIMED, not counted", p.stdout)
        self.assertIn("pin read @c (no own post, 2026-08-12) [CLAIMED, not counted]", p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_only_author_and_claimed_lines_are_unwitnessed(self):
        p = self.cover(spec=SPEC.replace(READ, AUTHOR_READ + CLAIMED_READ))
        self.assertIn("0 counted; 1 AUTHOR, 1 CLAIMED, not counted", p.stdout)
        self.assertIn("[UNWITNESSED] pin quote: no counted", p.stdout)
        self.assertIn("coverage: 1 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 1)

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_wrapped_author_marker_is_read(self):
        wrapped = "  - @b, event 9, 2026-08-10: pin 7 read against `abc1234`, 2\n    headings. AUTHOR.\n"
        p = self.cover(spec=SPEC.replace(READ, READ + wrapped))
        self.assertIn("1 counted (8); 1 AUTHOR", p.stdout)
        self.assertEqual(p.returncode, 0)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_author_line_still_asked_for_drift(self):
        p = self.cover(spec=SPEC.replace(READ, READ + AUTHOR_READ),
                       at_commit=DECISIONS.replace("## D-002 ·", "## Open · D-002 ·"))
        self.assertIn("[PIN READ DRIFT] pin quote: @b (event 7) [AUTHOR, not counted] read against",
                      p.stdout)
        self.assertEqual(p.returncode, 1)


class NotChecked(unittest.TestCase):
    """NOT CHECKED lists the events whose authorship is a reader's check
    (Kama, Lume #forge 2026-10-08), not the category. Not a gap."""

    cover = PinReads.cover

    @unittest.skipUnless(shutil.which("git"), "git not installed: the fixture's pin read can't be compared, so it isn't counted")
    def test_lists_pin_and_read_events(self):
        p = self.cover(spec=SPEC.replace(READ, READ + AUTHOR_READ + CLAIMED_READ))
        self.assertIn("NOT CHECKED: authorship of 7, 8 (Pulse not readable)", p.stdout)
        self.assertIn("coverage: 0 gap(s)", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_lists_pin_with_no_read_lines(self):
        p = self.cover(spec=SPEC.replace(READ, ""))
        self.assertIn("NOT CHECKED: authorship of 7 (Pulse not readable)", p.stdout)


if __name__ == "__main__":
    unittest.main()
