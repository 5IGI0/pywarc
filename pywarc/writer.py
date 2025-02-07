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

from io import BytesIO
from datetime import datetime
from uuid import uuid4

from .constants import PY_WARC_VERSION

DEFAULT_META={
    "format": "WARC File Format 1.1",
    "conformsTo": "http://bibnum.bnf.fr/WARC/WARC_ISO_28500_version1-1_latestdraft.pdf",
    "pywarc-version": PY_WARC_VERSION,
}

def _serialize_dict(d: dict) -> str:
    return ''.join([f"{k}: {v}\r\n" for k, v in d.items() if v is not None])

class WarcWriter(object):
    def __init__(self, file:[str|BytesIO], truncate=False, warc_meta={}, software_name="unknown", software_version="unkown"):
        if isinstance(file, str):
            self.fp = open(file, "ab+")
        else:
            self.fp = file

        # how many bytes we are waiting to complete the current block
        self.body_remaining_length = 0
        
        if self.fp.tell() == 0:
            actual_meta = {
                "software": f"{software_name}/{software_version}",
                **DEFAULT_META,
                **warc_meta}
            encoded_meta = _serialize_dict(actual_meta).encode("utf8")
            self.write_block("warcinfo", encoded_meta, record_meta={"Content-Type": "application/warc-fields"})

    def write_block(self, record_type: str, content: bytes, **kwargs):
        self.start_block(record_type, len(content), **kwargs)
        self.write_block_body(content)

    def start_block(self, record_type:str, content_length:int, record_id:[str|None]=None, record_date:[datetime|None]=None, record_meta:dict={}):
        assert(self.body_remaining_length == 0) # TODO: proper exception
        self.fp.write(b"WARC/1.1\r\n")
        
        if record_id is None:
            record_id = uuid4().urn
        if record_date is None:
            record_date = datetime.utcnow()
        
        self.fp.write((_serialize_dict({
            "WARC-Type":      record_type,
            "WARC-Record-ID": "<"+record_id+">",
            "WARC-Date":      record_date.isoformat(),
            **record_meta,
            "Content-Length": content_length})+"\r\n").encode("utf8"))
        
        self.body_remaining_length = content_length

    def write_block_body(self, content:bytes):
        assert(self.body_remaining_length >= len(content)) # TODO: proper exception
        self.fp.write(content)
        self.body_remaining_length -= len(content)
        if self.body_remaining_length == 0:
            self.fp.write(b"\r\n\r\n")

    def close(self):
        self.fp.close()
