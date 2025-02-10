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

import gzip

def MakeFakeTellable(obj):
    if hasattr(obj, 'seekable') and obj.seekable():
        return obj

    def _fake_tell():
        return obj.abc_pos

    def _fake_tell_write(*args, **kwargs):
        written = obj.abc_write(*args, **kwargs)
        obj.abc_pos += written
        return written

    obj.abc_pos = 0
    obj.tell = _fake_tell
    obj.abc_write = obj.write
    obj.write = _fake_tell_write
    
    return obj

def FakeSeekableWriter(fp):
    if hasattr(fp, 'start_part'):
        return fp

    if not hasattr(fp, 'tell'):
        fp = MakeFakeTellable(fp)

    fp.start_part = lambda: fp.tell()
    fp.end_part = lambda: fp.tell()
    
    return fp

class _NonClosableFP(object):
    def __init__(self, fp):
        self.fp = fp

    def write(self, *args, **kwargs):
        return self.fp.write(*args, **kwargs)

    def close(self, *args, **kwargs):
        return

class SeekableGZipWriter(object):
    def __init__(self, fp):
        self.sub_fp = MakeFakeTellable(fp)
        self.gzip_fp = None
    
    def start_part(self) -> int:
        assert(self.gzip_fp is None)
        pos = self.sub_fp.tell()
        self.gzip_fp = gzip.GzipFile(fileobj=_NonClosableFP(self.sub_fp), mode="w")
        return pos

    def end_part(self) -> int:
        assert(self.gzip_fp is not None)
        self.gzip_fp.close()
        self.gzip_fp = None
        return self.sub_fp.tell()

    def write(self, *args, **kwargs):
        assert(self.gzip_fp is not None)
        return self.gzip_fp.write(*args, **kwargs)

    def close(self):
        if self.gzip_fp is not None:
            self.end_part()
        
        self.sub_fp.close()
    
    def __del__(self):
        self.close()
