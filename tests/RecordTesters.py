# Copyright (C) 2025 5IGI0 / Ethan L. C. Lorenzetti
#
# This file is part of PyWarc.
# 
# PyWarc is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version.
#
# PyWarc is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License along with PyWarc.
# If not, see <https://www.gnu.org/licenses/>. 

import re
import unittest

from datetime import datetime, timezone, timedelta
from io import BytesIO

from pywarc import (
    ContentLengthMismatchError, InvalidWarcError, TruncatedWarcError,
    format_warc_date, iter_serialized_record, parse_record,
    serialize_record, serialize_record_head)

TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
DATE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,9})?Z")
CL = re.compile(r"0|[1-9][0-9]*")
FIXED_DATE = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def check_masstuffy(tc, data):
    """Small checker for the rules Masstuffy applies to what it accepts."""
    tc.assertTrue(data.startswith(b"WARC/1.1\r\n"))
    idx = data.index(b"\r\n\r\n")
    head = data[10:idx + 2]
    tc.assertLessEqual(idx + 4, 64 * 1024)
    names = []
    values = {}
    for line in head.split(b"\r\n")[:-1]:
        tc.assertIn(b": ", line)
        name, _, value = line.partition(b": ")
        tc.assertRegex(name, TOKEN)
        tc.assertIsNotNone(TOKEN.fullmatch(name))
        for b in value:
            tc.assertFalse((b < 0x20 and b != 9) or b == 0x7F)
        text = value.decode("utf-8")
        names.append(name.decode().lower())
        values.setdefault(name.decode().lower(), []).append(text)
    for k in ("warc-type", "warc-record-id", "warc-date", "content-length"):
        tc.assertEqual(names.count(k), 1, msg=k)
    tc.assertTrue(TOKEN.fullmatch(values["warc-type"][0].encode()))
    tc.assertIsNotNone(CL.fullmatch(values["content-length"][0]))
    rid = values["warc-record-id"][0]
    tc.assertTrue(rid.startswith("<") and rid.endswith(">"))
    inner = rid[1:-1]
    tc.assertIn(":", inner)
    for c in inner:
        tc.assertFalse(c <= " " or c in "<>\x7f")
    tc.assertIsNotNone(DATE.fullmatch(values["warc-date"][0]))
    body = data[idx + 4:]
    tc.assertTrue(body.endswith(b"\r\n\r\n"))
    tc.assertEqual(len(body) - 4, int(values["content-length"][0]))


class RecordTester(unittest.TestCase):
    def test_serialize_roundtrip(self):
        data = serialize_record(
            "resource", b"abc", record_id="urn:x:1", record_date=FIXED_DATE,
            record_headers={"WARC-Target-URI": "http://e.x/",
                            "WARC-Concurrent-To": ["<urn:a:1>", "<urn:a:2>"]})
        self.assertEqual(data, (
            b"WARC/1.1\r\nWARC-Type: resource\r\nWARC-Record-ID: <urn:x:1>\r\n"
            b"WARC-Date: 2020-01-02T03:04:05Z\r\nWARC-Target-URI: http://e.x/\r\n"
            b"WARC-Concurrent-To: <urn:a:1>\r\nWARC-Concurrent-To: <urn:a:2>\r\n"
            b"Content-Length: 3\r\n\r\nabc\r\n\r\n"))
        blk = parse_record(data)
        self.assertEqual(blk.type, "resource")
        self.assertEqual(blk.record_id, "urn:x:1")
        self.assertEqual(blk.date, FIXED_DATE)
        self.assertEqual(blk.target_uri, "http://e.x/")
        self.assertEqual(blk.concurrent_to, ["urn:a:1", "urn:a:2"])
        self.assertEqual(blk.content_length, 3)
        self.assertEqual(blk.read(), b"abc")
        self.assertEqual(blk.read(), b"")

    def test_parse_record_raw_head(self):
        data = serialize_record("resource", b"abc", record_id="urn:x:1", record_date=FIXED_DATE)
        self.assertEqual(parse_record(data).raw_head, data[:data.index(b"\r\n\r\n") + 4])

    def test_masstuffy_conformance(self):
        cases = [
            dict(content=b""),
            dict(content=b"x" * 1000),
            dict(content=b"\r\n\r\n"),
            dict(content=b"a", record_id="<urn:uuid:1>", record_headers={"X-A": 5, "X-B": "t\tv", "X-C": None}),
            dict(content=b"a", record_date=datetime(2020, 1, 2, 3, 4, 5, 999, tzinfo=timezone(timedelta(hours=2))),
                 record_headers={"Content-Type": "text/plain; charset=utf-8", "X-U": "caf\u00e9"}),
            dict(content=b"a", warcinfo_id="urn:x:w", record_date=datetime(900, 1, 1)),
        ]
        for case in cases:
            with self.subTest(case=case):
                content = case.pop("content")
                data = serialize_record("response", content, **case)
                check_masstuffy(self, data)
                self.assertEqual(parse_record(data).read(), content)
        check_masstuffy(self, serialize_record("response", b"d"))

    def test_no_warcinfo_id_by_default(self):
        self.assertNotIn(b"WARC-Warcinfo-ID", serialize_record("resource", b"a"))
        data = serialize_record("resource", b"a", warcinfo_id="urn:x:w")
        self.assertIn(b"WARC-Warcinfo-ID: <urn:x:w>\r\n", data)
        self.assertEqual(parse_record(data).warcinfo_id, "urn:x:w")

    def test_record_id_brackets(self):
        for rid in ("urn:x:1", "<urn:x:1>"):
            self.assertIn(b"WARC-Record-ID: <urn:x:1>\r\n", serialize_record("resource", b"", record_id=rid))
        for rid in ("nocolon", "a b:c", "", "<>", "a:<b"):
            with self.subTest(rid=rid):
                with self.assertRaises(ValueError):
                    serialize_record("resource", b"", record_id=rid)

    def test_reserved_headers(self):
        for hdrs in ({"warc-type": "x"}, {"CONTENT-LENGTH": "1"},
                     {"WARC-Date": "2020-01-01T00:00:00Z"}, {"warc-record-id": "<a:b>"}):
            with self.subTest(hdrs=hdrs):
                with self.assertRaises(ValueError):
                    serialize_record("resource", b"", record_headers=hdrs)
        with self.assertRaises(ValueError):
            serialize_record("resource", b"", warcinfo_id="urn:x:w", record_headers={"warc-warcinfo-id": "<a:b>"})
        # allowed when no warcinfo id is managed
        serialize_record("resource", b"", record_headers={"WARC-Warcinfo-ID": "<a:b>"})

    def test_header_injection(self):
        for hdrs in ({"X": "a\r\nX: b"}, {"X": "a\x00"}, {"X": "a\x7f"}, {"A B": "v"}, {"A:": "v"}, {"": "v"}):
            with self.subTest(hdrs=hdrs):
                with self.assertRaises(ValueError):
                    serialize_record("resource", b"", record_headers=hdrs)
        data = serialize_record("resource", b"", record_headers={"X": "a\tb", "Y": None, "Z": 5})
        self.assertIn(b"X: a\tb\r\n", data)
        self.assertNotIn(b"Y:", data)
        self.assertIn(b"Z: 5\r\n", data)

    def test_bad_record_type(self):
        for t in ("", "a b", "a\r\nb"):
            with self.assertRaises(ValueError):
                serialize_record(t, b"")
        for cl in (-1, "3", True, 1.5):
            with self.assertRaises(ValueError):
                serialize_record_head("resource", cl)

    def test_dates_format(self):
        self.assertEqual(format_warc_date(datetime(2020, 1, 2, 3, 4, 5)), "2020-01-02T03:04:05Z")
        aware = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(format_warc_date(aware), "2020-01-02T01:04:05Z")
        self.assertEqual(format_warc_date(datetime(2020, 1, 2, 3, 4, 5, 999999)), "2020-01-02T03:04:05Z")
        self.assertEqual(format_warc_date(datetime(900, 1, 2)), "0900-01-02T00:00:00Z")
        head = serialize_record_head("resource", 0).decode()
        m = re.search(r"WARC-Date: (\S+)\r\n", head)
        self.assertTrue(m.group(1).endswith("Z"))
        self.assertNotIn("+", m.group(1))

    def test_iter_serialized_record(self):
        kw = dict(record_id="urn:x:1", record_date=FIXED_DATE, record_headers={"X": "1"})
        body = b"0123456789"
        expected = serialize_record("resource", body, **kw)
        parts = list(iter_serialized_record("resource", len(body), BytesIO(body), **kw))
        self.assertEqual(b"".join(parts), expected)
        parts = list(iter_serialized_record("resource", len(body), [b"0123", b"", b"456789"], **kw))
        self.assertEqual(b"".join(parts), expected)
        parts = list(iter_serialized_record("resource", len(body), BytesIO(body), chunk_size=3, **kw))
        self.assertEqual(b"".join(parts), expected)
        self.assertGreater(len(parts), 2)

    def test_iter_validates_eagerly(self):
        with self.assertRaises(ValueError):
            iter_serialized_record("bad type", 0, [])

    def test_iter_bytes_body(self):
        kw = dict(record_id="urn:x:1", record_date=FIXED_DATE)
        for body in (b"\x01\x01\x01", bytearray(b"\x01\x01\x01"), memoryview(b"\x01\x01\x01")):
            parts = list(iter_serialized_record("resource", 3, body, **kw))
            self.assertEqual(b"".join(parts), serialize_record("resource", b"\x01\x01\x01", **kw))
        with self.assertRaises(TypeError):
            list(iter_serialized_record("resource", 3, [b"a", 3, b"b"], **kw))

    def test_content_length_limit(self):
        serialize_record_head("resource", 2 ** 64 - 1)
        with self.assertRaises(ValueError):
            serialize_record_head("resource", 2 ** 64)

    def test_iter_length_mismatch(self):
        for body in ([b"abc"], [b"abcdef"], [b"abcd", b"efgh"], BytesIO(b"abc")):
            with self.subTest(body=body):
                got = []
                with self.assertRaises(ContentLengthMismatchError):
                    for chunk in iter_serialized_record("resource", 5, body):
                        got.append(chunk)
                self.assertNotIn(b"\r\n\r\n", got[1:])  # trailer never yielded

    def test_parse_record_errors(self):
        good = serialize_record("resource", b"abc")
        with self.assertRaises(InvalidWarcError):
            parse_record(b"")
        with self.assertRaises(InvalidWarcError):
            parse_record(good + b"x")
        with self.assertRaises(InvalidWarcError):
            parse_record(good[:-4] + b"XXXX")
        with self.assertRaises(TruncatedWarcError):
            parse_record(good[:-4])
        with self.assertRaises(TruncatedWarcError):
            parse_record(good[:-6])
        with self.assertRaises(TruncatedWarcError):
            parse_record(good[:30])
