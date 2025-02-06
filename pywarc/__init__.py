# Copyright (C) 2025 5IGI0 / Ethan L. C. Lorenzetti
# 
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>. 

from io import BytesIO

MAX_SKIPBUF = 4096

class WarcBlock(object):
    def __init__(self, warc_reader, headers, block_content_pos):
        self.warc_reader = warc_reader
        self.block_content_pos = block_content_pos
        self.read_offset = 0
        self.headers = headers
        self.content_length = int(headers["Content-Length"][0])

    def read(self, nread=None):
        unread_data = self.content_length - self.read_offset

        if nread is None or nread > unread_data:
            nread = unread_data 

        ret = self.warc_reader.read_at(nread, self.block_content_pos + self.read_offset)
        self.read_offset += len(ret)
        return ret

    def get_as_stream(self):
        return BytesIO(self.warc_reader.read_at(self.content_length, self.block_content_pos))

class WarcReader(object):
    def __init__(self, fp):
        self.fp = fp
        self.is_seekable = fp.seekable()
        if self.is_seekable:
            self.current_pos = fp.tell()
        else:
            self.current_pos = 0
        self.next_block = self.current_pos

    def get_next_block(self):
        headers = b""

        self.skip_to(self.next_block)

        while True:
            tmp = self.fp.readline()

            if headers == b"" and tmp == b"": # no block anymore
                return None

            assert(headers != b"" or tmp == b"WARC/1.1\r\n") # TODO: proper exception

            headers += tmp
            if tmp == b"\r\n" or tmp == b"":
                break

        self.current_pos += len(headers)
        headers_dict = {}
        for header in  headers.splitlines()[1:]:
            if header == b"":
                break
            shdr = header.split(b": ")
            k = shdr[0].decode()
            v = (b": ".join(shdr[1:])).decode()
            headers_dict[k] = headers_dict[k].append(v) if k in headers_dict else [v]

        self.next_block = self.current_pos + int(headers_dict["Content-Length"][0]) + 4
        return WarcBlock(self, headers_dict, self.current_pos)

    def skip_to(self, at):
        if at == self.current_pos:
            return
        assert(at >= self.current_pos) # TODO: proper exception
        skip_nbytes = at - self.current_pos

        while skip_nbytes > 0:
            self.fp.read(MAX_SKIPBUF if skip_nbytes > MAX_SKIPBUF else skip_nbytes)
            skip_nbytes -= MAX_SKIPBUF
        
        self.current_pos = at

    def read_at(self, nread, at):
        if self.is_seekable:
            self.fp.seek(at)
            ret = self.read(nread)
            self.fp.seek(self.current_pos)
            return ret
        else:
            self.skip_to(at)
            ret = self.fp.read(nread)
            self.current_pos = len(ret) + at
            return ret

    def __next__(self):
        ret = self.get_next_block()
        if ret is None:
            raise StopIteration
        return ret

    def __iter__(self):
        return self