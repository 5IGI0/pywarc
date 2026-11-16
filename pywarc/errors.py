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

"""Exceptions raised by pywarc."""

from __future__ import annotations


class InvalidWarcError(Exception):
    """The input is not a valid WARC record."""


class MissingWarcHeaderError(InvalidWarcError):
    """A mandatory WARC header is not present."""


class WarcHeaderBadValueError(InvalidWarcError):
    """A WARC header contains an invalid value."""


class TruncatedWarcError(InvalidWarcError):
    """End of input reached inside a record head, body or trailer."""


class NotSeekableError(Exception):
    """The stream is not seekable and the requested data is behind the cursor."""


class PreviousBlockNotTerminatedError(Exception):
    """A new block was started while the previous one is incomplete."""


class CurrentBlockOverflowError(Exception):
    """More bytes were written than the current block declared."""


class ContentLengthMismatchError(CurrentBlockOverflowError):
    """A streamed body is shorter or longer than the declared Content-Length."""
