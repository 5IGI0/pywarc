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

import unittest
import tempfile
import shutil
import os
import gzip

from datetime import datetime, timezone
from pywarc import WarcReader, WarcWriter, InvalidWarcError, MissingWarcHeaderError, WarcHeaderBadValueError, NotSeekableError, TruncatedWarcError
from io import BytesIO
from .utils import patch_BytesIo

def ReaderTester(name, compressor, compressed):
    class ReaderTester(unittest.TestCase):
        def test_invalid_header_http(self):
            fp = BytesIO(compressor(b"HTTP/1.1 200 OK\r\nHost: example.org\r\nContent-Lenght: 5\r\n\r\nAAAAA"))
            reader = WarcReader(fp, compressed=compressed)

            with self.assertRaises(InvalidWarcError):
                reader.get_next_block()

        def test_empty_file(self):
            fp = BytesIO(compressor(b""))
            reader = WarcReader(fp, compressed=compressed)
            self.assertIsNone(reader.get_next_block())

        def test_invalid_record_header(self):
            fp = BytesIO(compressor(b"WARC/1.1\r\nA: B\r\nC: D\r\ndfxdfc\r\n\r\n"))
            reader = WarcReader(fp, compressed=compressed)
            with self.assertRaises(InvalidWarcError):
                reader.get_next_block()

        def test_no_content_length(self):
            fp = BytesIO(compressor(b"WARC/1.1\r\nWARC-Type: response\r\nWARC-Record-ID: <urn:test:1>\r\n\r\n"))
            reader = WarcReader(fp, compressed=compressed)
            with self.assertRaises(InvalidWarcError):
                reader.get_next_block()

        def test_missing_headers(self):
            fp = BytesIO(compressor(b"WARC/1.1\r\nContent-Length: 4\r\n\r\nAAAA\r\n\r\n"))

            block = WarcReader(fp, compressed=compressed).get_next_block()

            self.assertRaises(MissingWarcHeaderError, lambda: block.type)
            self.assertRaises(MissingWarcHeaderError, lambda: block.record_id)
            self.assertRaises(MissingWarcHeaderError, lambda: block.date)
            self.assertIsNone(block.content_type)
            self.assertIsNone(block.warcinfo_id)

        def test_invalid_headers(self):
            fp = BytesIO(compressor(
            b"WARC/1.1\r\nContent-Length: 4\r\n"
            b"WARC-Record-ID: rthdfswf\r\n"
            b"WARC-Warcinfo-ID: rtdfdf\r\n"
            b"WARC-Date: bonjour\r\n"
            b"\r\nAAAA\r\n\r\n"))

            block = WarcReader(fp, compressed=compressed).get_next_block()

            self.assertRaises(WarcHeaderBadValueError, lambda: block.record_id)
            self.assertRaises(WarcHeaderBadValueError, lambda: block.date)
            self.assertRaises(WarcHeaderBadValueError, lambda: block.warcinfo_id)


        # helpers

        def rec(self, headers=b"", body=b"", trailer=b"\r\n\r\n", version=b"WARC/1.1", length=None):
            if length is None:
                length = len(body)
            return version + b"\r\n" + headers + b"Content-Length: " + str(length).encode() + b"\r\n\r\n" + body + trailer

        def first(self, data, **kwargs):
            return WarcReader(BytesIO(compressor(data)), compressed=compressed, **kwargs).get_next_block()

        def test_repeated_headers(self):
            blk = self.first(self.rec(b"A: 1\r\nA: 2\r\nA: 3\r\n"))
            self.assertEqual(blk.headers["A"], ["1", "2", "3"])
            self.assertEqual(blk.header_all("a"), ["1", "2", "3"])
            self.assertEqual(blk.header("A"), "1")
            self.assertEqual(blk.header("nope", "dflt"), "dflt")
            blk.header_all("a").append("x")
            self.assertEqual(blk.header_all("a"), ["1", "2", "3"])

        def test_header_all_record_order(self):
            blk = self.first(self.rec(b"A: 1\r\na: 2\r\nA: 3\r\n"))
            self.assertEqual(blk.header_all("A"), ["1", "2", "3"])
            self.assertEqual(blk.headers["A"], ["1", "3"])

        def test_truncated_version_line(self):
            for data in (b"WARC/1.1", b"WARC/1.0\r", b"WARC/"):
                with self.assertRaises(TruncatedWarcError):
                    self.first(data)
            with self.assertRaises(InvalidWarcError):
                self.first(b"HTTP/1.1")

        def test_raw_head_exact(self):
            head = (b"WARC/1.1\r\nwarc-type:x\r\nA:   1  \r\nB: x\r\n\ty\r\nA: 2\r\n"
                    b"Content-Length: 3\r\n\r\n")
            blk = self.first(head + b"abc\r\n\r\n")
            self.assertEqual(blk.raw_head, head)
            self.assertEqual(blk.headers["A"], ["1", "2"])
            self.assertEqual(blk.header("B"), "x y")
            self.assertEqual(blk.type, "x")

        def test_reemit_warc_1_0(self):
            r1 = (b"WARC/1.0\r\nwarc-type:resource\r\nWARC-Target-URI:   http://e.x/ \r\n"
                  b"X: a\r\n  b\r\ncontent-length:5\r\n\r\nhello\r\n\r\n")
            r2 = b"WARC/1.0\r\nWARC-Type: metadata\r\nContent-Length: 0\r\n\r\n\r\n\r\n"
            body = b"\r\n\r\nWARC/1.0\r\n"
            r3 = (b"WARC/1.0\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body + b"\r\n\r\n")
            data = r1 + r2 + r3
            reader = WarcReader(BytesIO(compressor(data)), compressed=compressed)
            out = b"".join(chunk for blk in reader for chunk in blk.iter_raw(chunk_size=5))
            self.assertEqual(out, data)

        def test_iter_raw_after_partial_read(self):
            data = self.rec(b"A: 1\r\n", body=b"abcdefgh")
            blk = self.first(data)
            self.assertEqual(blk.read(3), b"abc")
            self.assertEqual(b"".join(blk.iter_raw()), data)

        def test_iter_raw_args(self):
            blk = self.first(self.rec())
            with self.assertRaises(ValueError):
                blk.iter_raw(chunk_size=0)
            blk.raw_head = None
            with self.assertRaises(ValueError):
                blk.iter_raw()

        def test_case_insensitive(self):
            blk = self.first(b"WARC/1.1\r\nwarc-type: x\r\ncontent-length: 4\r\n\r\nAAAA\r\n\r\n")
            self.assertEqual(blk.type, "x")
            self.assertEqual(blk.content_length, 4)
            self.assertEqual(blk.read(), b"AAAA")

        def test_warc_1_0(self):
            blk = self.first(self.rec(version=b"WARC/1.0"))
            self.assertEqual(blk.version, "WARC/1.0")
            self.assertEqual(self.first(self.rec()).version, "WARC/1.1")
            with self.assertRaises(InvalidWarcError):
                self.first(self.rec(version=b"WARC/2.0"))
            with self.assertRaises(InvalidWarcError):
                self.first(b"WARC/1.1\nContent-Length: 0\r\n\r\n\r\n\r\n")

        def test_header_whitespace(self):
            blk = self.first(self.rec(b"A:1\r\nB:   2  \r\nC:\t3\r\n"))
            self.assertEqual(blk.header("A"), "1")
            self.assertEqual(blk.header("B"), "2")
            self.assertEqual(blk.header("C"), "3")

        def test_folded_header(self):
            blk = self.first(self.rec(b"A: x\r\n  y\r\n"))
            self.assertEqual(blk.header("A"), "x y")
            with self.assertRaises(InvalidWarcError):
                self.first(b"WARC/1.1\r\n  y\r\nContent-Length: 0\r\n\r\n\r\n\r\n")

        def test_bad_names(self):
            for hdr in (b": v\r\n", b"A B: v\r\n", "A\u00e9: v\r\n".encode()):
                with self.subTest(hdr=hdr):
                    with self.assertRaises(InvalidWarcError):
                        self.first(self.rec(hdr))

        def test_invalid_utf8_value(self):
            with self.assertRaises(InvalidWarcError):
                self.first(self.rec(b"A: \xff\r\n"))

        def test_bare_lf(self):
            with self.assertRaises(InvalidWarcError):
                self.first(self.rec(b"A: 1\n"))

        def test_content_length_rules(self):
            for cl in (b"-1", b"05", b"5_0", b"+5", b" 5x", b""):
                with self.subTest(cl=cl):
                    with self.assertRaises(InvalidWarcError):
                        self.first(b"WARC/1.1\r\nContent-Length: " + cl + b"\r\n\r\nAAAAA\r\n\r\n")
            with self.assertRaises(InvalidWarcError):
                self.first(b"WARC/1.1\r\nContent-Length: 1\r\ncontent-length: 1\r\n\r\nA\r\n\r\n")

        def test_truncated_head(self):
            with self.assertRaises(TruncatedWarcError):
                self.first(b"WARC/1.1\r\nContent-Length: 4\r\nA: b")
            with self.assertRaises(TruncatedWarcError):
                self.first(b"WARC/1.1\r\nContent-Length: 4\r\n")

        def test_truncated_body(self):
            blk = self.first(self.rec(body=b"abc", length=10, trailer=b""))
            with self.assertRaises(TruncatedWarcError):
                blk.read()

        def test_bad_trailer(self):
            r = WarcReader(BytesIO(compressor(self.rec(trailer=b"XXXX") + self.rec())), compressed=compressed)
            r.get_next_block()
            with self.assertRaises(InvalidWarcError):
                r.get_next_block()
            r = WarcReader(BytesIO(compressor(self.rec(body=b"ab", trailer=b""))), compressed=compressed)
            r.get_next_block()
            with self.assertRaises(TruncatedWarcError):
                r.get_next_block()

        def test_header_cap(self):
            data = b"WARC/1.1\r\nA: " + b"x" * 200 + b"\r\nContent-Length: 0\r\n\r\n\r\n\r\n" + b"y" * 100000
            fp = BytesIO(compressor(data))
            r = WarcReader(fp, compressed=compressed, max_header_bytes=100)
            with self.assertRaises(InvalidWarcError):
                r.get_next_block()
            if not compressed:
                self.assertLessEqual(fp.tell(), 200)

        def test_max_headers(self):
            data = self.rec(b"A: 1\r\nB: 2\r\n")  # 3 headers with Content-Length
            with self.assertRaises(InvalidWarcError):
                self.first(data, max_headers=2)
            self.assertIsNotNone(self.first(data, max_headers=3))

        def test_accessors(self):
            blk = self.first(self.rec(
                b"WARC-Target-URI: http://e.x/\r\nWARC-Payload-Digest: sha1:AA\r\n"
                b"WARC-Block-Digest: sha1:BB\r\nWARC-Refers-To: <urn:a:1>\r\n"
                b"WARC-Concurrent-To: <urn:a:2>\r\nWARC-Concurrent-To: <urn:a:3>\r\n"))
            self.assertEqual(blk.target_uri, "http://e.x/")
            self.assertEqual(blk.payload_digest, "sha1:AA")
            self.assertEqual(blk.block_digest, "sha1:BB")
            self.assertEqual(blk.refers_to, "urn:a:1")
            self.assertEqual(blk.concurrent_to, ["urn:a:2", "urn:a:3"])
            blk = self.first(self.rec(b"WARC-Target-URI: <http://e.x/>\r\nWARC-Refers-To: urn:a:1\r\n"))
            self.assertEqual(blk.target_uri, "http://e.x/")
            self.assertRaises(WarcHeaderBadValueError, lambda: blk.refers_to)
            blk = self.first(self.rec())
            self.assertIsNone(blk.target_uri)
            self.assertIsNone(blk.refers_to)
            self.assertEqual(blk.concurrent_to, [])

        def test_dates(self):
            utc = timezone.utc
            ok = {
                "2020-01-02T03:04:05Z": datetime(2020, 1, 2, 3, 4, 5, tzinfo=utc),
                "2020-01-02T03:04:05.123456789Z": datetime(2020, 1, 2, 3, 4, 5, 123456, tzinfo=utc),
                "2020-01-02T03:04Z": datetime(2020, 1, 2, 3, 4, tzinfo=utc),
                "2020": datetime(2020, 1, 1, tzinfo=utc),
                "2020-01": datetime(2020, 1, 1, tzinfo=utc),
                "2020-01-02": datetime(2020, 1, 2, tzinfo=utc),
                "2020-01-02T05:04:05+02:00": datetime(2020, 1, 2, 3, 4, 5, tzinfo=utc),
            }
            for text, expected in ok.items():
                with self.subTest(date=text):
                    d = self.first(self.rec(b"WARC-Date: " + text.encode() + b"\r\n")).date
                    self.assertEqual(d, expected)
                    self.assertEqual(d.utcoffset().total_seconds(), 0)
            for text in ("2020-01-02T03:04:05", "2020-13-01T00:00:00Z", "bonjour"):
                with self.subTest(date=text):
                    blk = self.first(self.rec(b"WARC-Date: " + text.encode() + b"\r\n"))
                    self.assertRaises(WarcHeaderBadValueError, lambda: blk.date)

    ReaderTester.__name__ = name
    ReaderTester.__qualname__ = name
    return ReaderTester

GzipReaderTester = ReaderTester("GzipReaderTester", gzip.compress, True)
ReaderTester = ReaderTester("ReaderTester", lambda x: x, False)

def SeekableReaderTester(name, compressed):
    class SeekableReaderTester(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.fp = BytesIO(b"")
            writer = WarcWriter(cls.fp, compress=compressed)
            cls.block_contents = [os.urandom(300) for _ in range(3)]
            for b in cls.block_contents:
                writer.write_block("resource", b)

        def test_proper_seek(self):
            self.fp.seek(0)

            reader = WarcReader(self.fp, compressed=compressed)
            warc_block = reader.get_next_block()

            first_block = reader.get_next_block()
            second_block = reader.get_next_block()

            self.assertEqual(first_block.read(), self.block_contents[0])
            third_block = reader.get_next_block()
            self.assertEqual(third_block.read(20), self.block_contents[2][:20])
            self.assertEqual(second_block.read(), self.block_contents[1])
            self.assertEqual(third_block.read(), self.block_contents[2][20:])

    SeekableReaderTester.__name__ = name
    SeekableReaderTester.__qualname__ = name
    return SeekableReaderTester

GzipSeekableReaderTester = SeekableReaderTester("GzipSeekableReaderTester", True)
SeekableReaderTester = SeekableReaderTester("SeekableReaderTester", False)

class ShortReadStream(object):
    """Non-seekable stream whose read(n) returns at most 7 bytes."""
    def __init__(self, data):
        self._b = BytesIO(data)

    def seekable(self):
        return False

    def read(self, n=-1):
        return self._b.read(7 if n is None or n < 0 else min(n, 7))

    def readline(self, limit=-1):
        return self._b.readline(limit)


class ReadOnlyStream(object):
    """Object exposing only read/readline."""
    def __init__(self, data):
        self._b = BytesIO(data)

    def read(self, n=-1):
        return self._b.read(n)

    def readline(self, limit=-1):
        return self._b.readline(limit)


def NonSeekableReaderTester(name, compressed):
    class NonSeekableReaderTester(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.fp = patch_BytesIo(False)(b"")
            writer = WarcWriter(cls.fp, compress=compressed)
            cls.block_contents = [os.urandom(300) for _ in range(2)]
            for b in cls.block_contents:
                writer.write_block("resource", b)

        def test_proper_non_seek(self):
            self.fp.force_seek(0)

            reader = WarcReader(self.fp, compressed=compressed)
            warc_block = reader.get_next_block()

            first_block = reader.get_next_block()
            self.assertEqual(first_block.read(10), self.block_contents[0][:10])

            second_block = reader.get_next_block()
            self.assertRaises(NotSeekableError, lambda: first_block.read())

            self.assertEqual(second_block.read(), self.block_contents[1])

        def _plain_data(self):
            buf = BytesIO()
            w = WarcWriter(buf, compress=False)
            bodies = [os.urandom(300) for _ in range(3)]
            for b in bodies:
                w.write_block("resource", b)
            return buf.getvalue(), bodies

        def test_short_reads(self):
            data, bodies = self._plain_data()
            r = WarcReader(ShortReadStream(data), compressed=False)
            r.get_next_block()  # warcinfo
            for expected in bodies:
                self.assertEqual(r.get_next_block().read(), expected)
            self.assertIsNone(r.get_next_block())

            # skip bodies without reading them
            r = WarcReader(ShortReadStream(data), compressed=False)
            r.get_next_block()
            r.get_next_block()
            self.assertEqual(r.get_next_block().read(), bodies[1])
            r.get_next_block()  # skipped
            self.assertIsNone(r.get_next_block())

        def test_stream_without_seekable_method(self):
            data, bodies = self._plain_data()
            r = WarcReader(ReadOnlyStream(data), compressed=False)
            r.get_next_block()
            self.assertEqual(r.get_next_block().read(), bodies[0])

        def test_iter_raw_streaming(self):
            data, bodies = self._plain_data()
            r = WarcReader(ShortReadStream(data), compressed=False)
            out = b"".join(c for blk in r for c in blk.iter_raw(chunk_size=50))
            self.assertEqual(out, data)
            r = WarcReader(ShortReadStream(data), compressed=False)
            r.get_next_block()
            blk = r.get_next_block()
            blk.read(10)
            with self.assertRaises(NotSeekableError):
                list(blk.iter_raw())

        def test_iter_raw_partial_read_fails_early(self):
            data, _ = self._plain_data()
            r = WarcReader(ShortReadStream(data), compressed=False)
            r.get_next_block()
            blk = r.get_next_block()
            blk.read(10)
            gen = None
            with self.assertRaises(NotSeekableError):
                gen = blk.iter_raw()  # raises at call time, nothing yielded
            self.assertIsNone(gen)

    NonSeekableReaderTester.__name__ = name
    NonSeekableReaderTester.__qualname__ = name
    return NonSeekableReaderTester

GzipNonSeekableReaderTester = NonSeekableReaderTester("GzipNonSeekableReaderTester", True)
NonSeekableReaderTester = NonSeekableReaderTester("NonSeekableReaderTester", False)


class CountingBytesIO(BytesIO):
    """BytesIO that counts bytes handed out and seek calls."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bytes_read = 0
        self.seeks = 0

    def read(self, *args, **kwargs):
        ret = super().read(*args, **kwargs)
        self.bytes_read += len(ret)
        return ret

    def read1(self, *args, **kwargs):
        ret = super().read1(*args, **kwargs)
        self.bytes_read += len(ret)
        return ret

    def readinto(self, b):
        n = super().readinto(b)
        self.bytes_read += n
        return n

    def seek(self, *args, **kwargs):
        self.seeks += 1
        return super().seek(*args, **kwargs)


class GzipLinearReadTester(unittest.TestCase):
    N = 200

    @classmethod
    def setUpClass(cls):
        buf = BytesIO()
        w = WarcWriter(buf, compress=True)
        cls.bodies = [os.urandom(20000) for _ in range(cls.N)]
        for b in cls.bodies:
            w.write_block("resource", b)
        cls.data = buf.getvalue()

    def _reader(self):
        raw = CountingBytesIO(self.data)
        reader = WarcReader(raw, compressed=True)
        calls = []
        orig = reader.fp.seek
        def counting_seek(*a, **k):
            calls.append(a)
            return orig(*a, **k)
        reader.fp.seek = counting_seek
        return raw, reader, calls

    def test_sequential_read_is_linear(self):
        raw, reader, calls = self._reader()
        reader.get_next_block()  # warcinfo
        for expected in self.bodies:
            blk = reader.get_next_block()
            out = []
            while True:
                chunk = blk.read(4096)
                if not chunk:
                    break
                out.append(chunk)
            self.assertEqual(b"".join(out), expected)
        self.assertIsNone(reader.get_next_block())
        self.assertLessEqual(raw.bytes_read, len(self.data) + 256 * 1024)
        self.assertEqual(calls, [])

    def test_get_as_stream_is_linear(self):
        raw, reader, calls = self._reader()
        reader.get_next_block()
        for expected in self.bodies:
            self.assertEqual(reader.get_next_block().get_as_stream().read(), expected)
        self.assertLessEqual(raw.bytes_read, len(self.data) + 256 * 1024)
        self.assertEqual(calls, [])


class PlainSkipTester(unittest.TestCase):
    def _data(self, n=50):
        buf = BytesIO()
        w = WarcWriter(buf, compress=False)
        bodies = [bytes([i]) * 100000 for i in range(n)]
        for b in bodies:
            w.write_block("resource", b)
        return buf.getvalue(), bodies

    def test_skip_uses_seek(self):
        data, bodies = self._data()
        raw = CountingBytesIO(data)
        reader = WarcReader(raw, compressed=False)
        last = None
        for blk in reader:
            last = blk
        self.assertLess(raw.bytes_read, len(data) // 10)
        self.assertEqual(last.type, "resource")
        self.assertEqual(last.content_length, 100000)
        self.assertEqual(last.read(), bodies[-1])

    def test_truncated_last_body(self):
        data, _ = self._data(3)
        reader = WarcReader(BytesIO(data[:-50000]), compressed=False)
        for _ in range(4):  # warcinfo + 3 records, the last one cut
            reader.get_next_block()
        with self.assertRaises(TruncatedWarcError):
            reader.get_next_block()


class GzipDamagedTester(unittest.TestCase):
    def _gz(self):
        buf = BytesIO()
        w = WarcWriter(buf, compress=True)
        body = os.urandom(5000)
        w.write_block("resource", body)
        return buf.getvalue(), body

    def test_cut_member(self):
        data, body = self._gz()
        cut = data[:-100]
        reader = WarcReader(BytesIO(cut), compressed=True)
        reader.get_next_block()
        blk = reader.get_next_block()
        with self.assertRaises(TruncatedWarcError) as cm:
            blk.read()
        self.assertIsInstance(cm.exception.__cause__, EOFError)
        # position stays consistent with what was really read
        self.assertLessEqual(reader.current_pos, blk.block_content_pos + blk.content_length)
        # cut inside the head of the record
        reader = WarcReader(BytesIO(data[:60]), compressed=True)
        with self.assertRaises(TruncatedWarcError):
            reader.get_next_block()

    def test_corrupted_member(self):
        data, body = self._gz()
        bad = bytearray(data)
        bad[len(bad) // 2] ^= 0xFF
        reader = WarcReader(BytesIO(bytes(bad)), compressed=True)
        with self.assertRaises(InvalidWarcError):
            for blk in reader:
                blk.read()
