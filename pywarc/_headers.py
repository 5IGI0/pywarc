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

"""Private helpers shared by the reader and the writer."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .errors import InvalidWarcError

# RFC 9110 tchar
TCHARS = frozenset(
    b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

_CL_RE = re.compile(r"0|[1-9][0-9]{0,19}")
_DATE_RE = re.compile(
    r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2})"
    r"(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,9}))?)?"
    r"(Z|[+-][0-9]{2}:[0-9]{2}))?)?)?"
)


def is_token(s: str) -> bool:
    """True if `s` is a non-empty RFC 9110 token (ASCII only)."""
    return len(s) > 0 and all(ord(c) in TCHARS for c in s)


def check_header_value(v: str) -> None:
    """Raise ValueError if `v` has a control character (other than HT) or DEL."""
    for c in v:
        if (c < " " and c != "\t") or c == "\x7f":
            raise ValueError("header value contains a control character: %r" % (v,))


def check_record_id(inner: str) -> None:
    """Raise ValueError unless `inner` (without brackets) is a valid record id."""
    if not inner or ":" not in inner:
        raise ValueError("invalid record id (must be a URI containing ':'): %r" % (inner,))
    for c in inner:
        if c <= " " or c in "<>" or c == "\x7f":
            raise ValueError("invalid character in record id: %r" % (inner,))


def strip_brackets(v: str) -> str:
    """'<x>' -> 'x'; anything else is returned unchanged."""
    if len(v) >= 2 and v[0] == "<" and v[-1] == ">":
        return v[1:-1]
    return v


def parse_content_length(v: str) -> int:
    """Parse a canonical decimal Content-Length, else raise InvalidWarcError."""
    if _CL_RE.fullmatch(v) is None:
        raise InvalidWarcError("invalid Content-Length: %r" % (v,))
    return int(v)


def parse_warc_date(s: str) -> datetime:
    """Parse a WARC-Date (W3C-ISO8601 profiles) to a tz-aware UTC datetime.

    Raises ValueError on invalid input. Date-only forms mean midnight UTC;
    a time part requires a TZD ('Z' or '+hh:mm'/'-hh:mm').
    """
    m = _DATE_RE.fullmatch(s)
    if m is None:
        raise ValueError("invalid WARC-Date: %r" % (s,))
    year, month, day, hour, minute, sec, frac, tzd = m.groups()
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = timedelta(0)
    if tzd is not None and tzd != "Z":
        oh, om = int(tzd[1:3]), int(tzd[4:6])
        if oh > 23 or om > 59:
            raise ValueError("invalid time zone in WARC-Date: %r" % (s,))
        offset = timedelta(hours=oh, minutes=om)
        if tzd[0] == "-":
            offset = -offset
    dt = datetime(
        int(year), int(month or 1), int(day or 1),
        int(hour or 0), int(minute or 0), int(sec or 0), micro,
        tzinfo=timezone.utc,
    )
    try:
        return dt - offset
    except OverflowError as e:
        raise ValueError("WARC-Date out of range: %r" % (s,)) from e


def format_warc_date(d: datetime) -> str:
    """Format `d` as YYYY-MM-DDThh:mm:ssZ (seconds precision).

    A naive datetime is assumed to be UTC; an aware one is converted to UTC.
    """
    if d.tzinfo is not None and d.utcoffset() is not None:
        d = d.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second)
