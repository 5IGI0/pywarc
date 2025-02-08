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

from pywarc import WarcReader, WarcWriter, InvalidWarcError, MissingWarcHeaderError, WarcHeaderBadValueError, NotSeekableError
from io import BytesIO
from .utils import patch_BytesIo

class ReaderTester(unittest.TestCase):
    def test_invalid_header_http(self):
        fp = BytesIO(b"HTTP/1.1 200 OK\r\nHost: example.org\r\nContent-Lenght: 5\r\n\r\nAAAAA")
        reader = WarcReader(fp)

        with self.assertRaises(InvalidWarcError):
            reader.get_next_block()

    def test_empty_file(self):
        fp = BytesIO(b"")
        reader = WarcReader(fp)
        self.assertIsNone(reader.get_next_block())

    def test_invalid_record_header(self):
        fp = BytesIO(b"WARC/1.1\r\nA: B\r\nC: D\r\ndfxdfc\r\n\r\n")
        reader = WarcReader(fp)
        with self.assertRaises(InvalidWarcError):
            reader.get_next_block()

    def test_no_content_length(self):
        fp = BytesIO(b"WARC/1.1\r\nWARC-Type: response\r\nWARC-Record-ID: <urn:test:1>\r\n\r\n")
        reader = WarcReader(fp)
        with self.assertRaises(InvalidWarcError):
            reader.get_next_block()

    def test_missing_headers(self):
        fp = BytesIO(b"WARC/1.1\r\nContent-Length: 4\r\n\r\nAAAA\r\n\r\n")

        block = WarcReader(fp).get_next_block()

        self.assertRaises(MissingWarcHeaderError, lambda: block.type)
        self.assertRaises(MissingWarcHeaderError, lambda: block.record_id)
        self.assertRaises(MissingWarcHeaderError, lambda: block.date)
        self.assertIsNone(block.content_type)
        self.assertIsNone(block.warcinfo_id)

    def test_invalid_headers(self):
        fp = BytesIO(
        b"WARC/1.1\r\nContent-Length: 4\r\n"
        b"WARC-Record-ID: rthdfswf\r\n"
        b"WARC-Warcinfo-ID: rtdfdf\r\n"
        b"WARC-Date: bonjour\r\n"
        b"\r\nAAAA\r\n\r\n")

        block = WarcReader(fp).get_next_block()

        self.assertRaises(WarcHeaderBadValueError, lambda: block.record_id)
        self.assertRaises(WarcHeaderBadValueError, lambda: block.date)
        self.assertRaises(WarcHeaderBadValueError, lambda: block.warcinfo_id)

class SeekableReaderTester(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = BytesIO(b"")
        writer = WarcWriter(cls.fp)
        cls.block_contents = [os.urandom(300) for _ in range(3)]
        for b in cls.block_contents:
            writer.write_block("resource", b)

    def test_proper_seek(self):
        self.fp.seek(0)

        reader = WarcReader(self.fp)
        warc_block = reader.get_next_block()

        first_block = reader.get_next_block()
        second_block = reader.get_next_block()

        self.assertEqual(first_block.read(), self.block_contents[0])
        third_block = reader.get_next_block()
        self.assertEqual(third_block.read(20), self.block_contents[2][:20])
        self.assertEqual(second_block.read(), self.block_contents[1])
        self.assertEqual(third_block.read(), self.block_contents[2][20:])

class NonSeekableReaderTester(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = patch_BytesIo(False)(b"")
        writer = WarcWriter(cls.fp)
        cls.block_contents = [os.urandom(300) for _ in range(2)]
        for b in cls.block_contents:
            writer.write_block("resource", b)

    def test_proper_non_seek(self):
        self.fp.force_seek(0)

        reader = WarcReader(self.fp)
        warc_block = reader.get_next_block()

        first_block = reader.get_next_block()
        self.assertEqual(first_block.read(10), self.block_contents[0][:10])

        second_block = reader.get_next_block()
        self.assertRaises(NotSeekableError, lambda: first_block.read())

        self.assertEqual(second_block.read(), self.block_contents[1])