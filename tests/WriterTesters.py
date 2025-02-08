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
import re
import os

from datetime import datetime
from pywarc import WarcReader, WarcWriter, CurrentBlockOverflowError, PreviousBlockNotTerminatedError
from random import choices, randint
from .utils import patch_BytesIo

MAX_CONTENT_LENGTH=5_000_000

class WriterTester(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir)

    def test_truncate(self):
        path = self.temp_dir+"/truncate_test.warc"

        warc = WarcWriter(path, truncate=True)
        warc.write_block("yrhdfdf", b"ryhtgdfdf")
        warc.write_block("yrhdfdf", b"ryhtgdfdf")
        warc.write_block("yrhdfdf", b"ryhtgdfdf")
        before_truncate = warc.fp.tell()
        del warc

        warc = WarcWriter(path, truncate=True)
        warc.write_block("yrhdfdf", b"ryhtgdfdf")
        after_truncate = warc.fp.tell()
        del warc

        self.assertLessEqual(after_truncate, before_truncate, "WarcWriter didn't truncate")

        warc = WarcWriter(path, truncate=False)
        warc.write_block("yrhdfdf", b"ryhtgdfdf")
        after_append = warc.fp.tell()
        del warc

        self.assertGreaterEqual(after_append, after_truncate, "WarcWriter didn't truncate")

        # validate it is still a valid file after appending
        reader = WarcReader(path)
        for _ in reader:
            pass

def gen_tester(name, PatchedBytesIO):
    class WriterTester(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.warcinfo = {
                        os.urandom(randint(1, 10)).hex(): os.urandom(randint(1, 10)).hex()
                        for _ in range(5)}

            cls.testset = [{"content": b"", "custom_headers":{
                        os.urandom(randint(1, 10)).hex(): os.urandom(randint(1, 10)).hex()
                        for _ in range(5)}}]
            
            for i in range(10):
                cls.testset.append({
                    "content": os.urandom(randint(0, MAX_CONTENT_LENGTH)),
                    "custom_headers": {
                        os.urandom(randint(1, 10)).hex(): os.urandom(randint(1, 10)).hex()
                        for _ in range(5)}})

        def validate_block(self, block):
            with self.subTest("check mandatory headers"):
                for k in ("WARC-Type", "WARC-Date", "WARC-Record-ID", "Content-Length"):
                    self.assertIn(k, block.headers, msg=f"'{k}' not in block's headers")

            with self.subTest("check for duplicate WARC headers"):
                for k, v in block.headers.items():
                    # some WARC headers can be duplicate but
                    # we don't generate them, we dont need to check that.
                    if k.startswith("WARC-") or k in ["Content-Length", "Content-Type"]:
                        self.assertEqual(len(v), 1, msg=f"'{k}' has duplicate keys")

            with self.subTest("validate WARC headers"):
                self.assertIsNotNone(re.fullmatch(
                        "^urn:uuid:[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[a-f0-9]{4}-[a-f0-9]{12}$", block.record_id),
                        msg="'WARC-Record-ID' is not a UUID")
                try:
                    self.assertIsNotNone(block.date, msg="date is None")
                except:
                    self.fail("WARC-Date has invalid date")
                self.assertIn(block.type, (
                    "warcinfo", "response", "resource",
                    "request", "metadata", "revisit",
                    "conversion", "continuation"))
                self.assertIsInstance(block.content_length, int)

            if block.type == "warcinfo":
                with self.subTest("validate warcinfo block"):
                    self.assertTrue(block.content_type == "application/warc-fields", msg="warcinfo content-type is not 'application/warc-fields'")
                    stream = block.get_as_stream()
                    for line in stream:
                        self.assertTrue(b': ' in line and line.endswith(b'\r\n'), msg="invalid warcinfo line")

        def validate_warc(self, fp):
            with self.subTest("validate archive"):
                reader = WarcReader(fp)

                first_block = reader.get_next_block()
                self.assertEqual(first_block.type, "warcinfo")
                self.validate_block(first_block)
                current_warc_info_id = first_block.record_id

                for block in reader:
                    self.assertEqual(current_warc_info_id, block.warcinfo_id)
                    self.validate_block(block)

        def check_content(self, fp):
            with self.subTest("check content"):
                reader = WarcReader(fp)

                first_block = reader.get_next_block()
                with self.subTest("check that users' fields are present"):
                    stream = first_block.get_as_stream()
                    is_present = {k: False for k in self.warcinfo}
                    for line in stream:
                        line = line.split(b': ')
                        k = line[0].decode()
                        v = b': '.join(line[1:])[:-2].decode()
                        if k in self.warcinfo:
                            self.assertEqual(v, self.warcinfo[k], msg=f"'{k}' value doesn't match with expected one")
                            is_present[k] = True
                    
                    for k, v in is_present.items():
                        self.assertTrue(v, msg=f"'{k}' is not present in warcinfo")

            with self.subTest("check that users' block headers are present"):
                i = -1
                for block in reader:
                    i += 1
                    self.assertEqual(block.read(), self.testset[i]["content"])
                    is_present = {k: False for k in self.testset[i]["custom_headers"]}
                    for k, v in block.headers.items():
                        if k in is_present:
                            self.assertEqual(v[0], self.testset[i]["custom_headers"][k], msg=f"'{k}' value doesn't match with expected one")
                            is_present[k] = True
                    
                    for k, v in is_present.items():
                        self.assertTrue(v, msg=f"'{k}' is not present in the block header")

        def test_write_block(self):
            underlaying_fp = PatchedBytesIO(b"")
            writer = WarcWriter(
                underlaying_fp,
                software_name="unittester",
                software_version="0.0.0",
                warc_meta=self.warcinfo)

            for block in self.testset:
                writer.write_block("resource", block["content"], record_headers=block["custom_headers"])
            
            underlaying_fp.force_seek(0) # do not use it in your code to bypass the tests.
            self.validate_warc(underlaying_fp)
            underlaying_fp.force_seek(0) # do not use it in your code to bypass the tests.
            self.check_content(underlaying_fp)
        
        def test_write_chunked_block(self):
            underlaying_fp = PatchedBytesIO(b"")
            writer = WarcWriter(
                underlaying_fp,
                software_name="unittester",
                software_version="0.0.0",
                warc_meta=self.warcinfo)

            for block in self.testset:
                writer.start_block("resource", len(block["content"]), record_headers=block["custom_headers"])
                curlen = len(block["content"])
                curoff = 0
                writer.write_block_body(b"")
                while curoff < curlen:
                    part_size = randint(0, curlen-curoff)
                    writer.write_block_body(block["content"][curoff:curoff+part_size])
                    curoff+=part_size
                writer.write_block_body(b"")
            
            underlaying_fp.force_seek(0) # do not use it in your code to bypass the tests.
            self.validate_warc(underlaying_fp)
            underlaying_fp.force_seek(0) # do not use it in your code to bypass the tests.
            self.check_content(underlaying_fp)

        def test_overflow_and_not_terminated(self):
            underlaying_fp = PatchedBytesIO(b"")
            writer = WarcWriter(
                underlaying_fp,
                software_name="unittester",
                software_version="0.0.0",
                warc_meta=self.warcinfo)

            self.assertRaises(CurrentBlockOverflowError, lambda: writer.write_block_body(b"rtdffg"))

            writer.start_block("test", 10)
            writer.write_block_body(b"12345")
            self.assertRaises(CurrentBlockOverflowError, lambda: writer.write_block_body(b"123456"))
            self.assertRaises(PreviousBlockNotTerminatedError, lambda: writer.start_block("test", 10))
            self.assertRaises(PreviousBlockNotTerminatedError, lambda: writer.write_block("test", b"bonsoir"))
            writer.write_block_body(b"12345")

    WriterTester.__name__ = name
    WriterTester.__qualname__ = name
    return WriterTester
    
SeekableWriterTester = gen_tester("SeekableWriteTester", patch_BytesIo(True))
NotSeekableWriterTester = gen_tester("NonSeekableWriteTester", patch_BytesIo(False))