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

def patch_BytesIo(seekable):
    class PatchedByteIO(BytesIO):
        def seekable(self):
            return seekable

        def seek(self, *args, **kwargs):
            if seekable:
                return super().seek(*args, **kwargs)
            else:
                raise Exception("shouldn't have use seek() on non-seekable file")

        def force_seek(self, *args, **kwargs):
            return super().seek(*args, **kwargs)
    return PatchedByteIO