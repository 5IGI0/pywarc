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

from __future__ import annotations

from datetime import datetime, timezone
from typing import IO, Dict, Iterable, Iterator, Optional, Tuple, Union
from uuid import uuid4

from ._headers import check_header_value, check_record_id, format_warc_date, is_token, strip_brackets
from .compression import FakeSeekableWriter, MakeFakeTellable, SeekableGZipWriter
from .constants import PY_WARC_VERSION
from .errors import (  # noqa: F401  (re-exported for backward compatibility)
    ContentLengthMismatchError,
    CurrentBlockOverflowError,
    PreviousBlockNotTerminatedError,
)

DEFAULT_META = {
    "format": "WARC File Format 1.1",
    "conformsTo": "http://bibnum.bnf.fr/WARC/WARC_ISO_28500_version1-1_latestdraft.pdf",
    "pywarc-version": PY_WARC_VERSION,
}

_RESERVED = ("warc-type", "warc-record-id", "warc-date", "content-length")
_TRAILER = b"\r\n\r\n"


def _serialize_dict(d: dict) -> str:
    """Serialize `application/warc-fields` content (used for the warcinfo payload)."""
    out = []
    for k, v in d.items():
        if v is None:
            continue
        k, v = str(k), str(v)
        if not is_token(k):
            raise ValueError("invalid header name: %r" % (k,))
        check_header_value(v)
        out.append(f"{k}: {v}\r\n")
    return "".join(out)


def _clean_uri(value: str, what: str) -> str:
    inner = strip_brackets(value)
    try:
        check_record_id(inner)
    except ValueError as e:
        raise ValueError(f"invalid {what}: {value!r}") from e
    return inner


def serialize_record_head(record_type: str, content_length: int, record_id: Optional[str] = None,
                          record_date: Optional[datetime] = None, record_headers: Optional[dict] = None,
                          warcinfo_id: Optional[str] = None) -> bytes:
    """WARC/1.1 version line + headers + blank line, UTF-8.

    Header order: WARC-Type, WARC-Record-ID, [WARC-Warcinfo-ID], WARC-Date,
    user headers in dict order, Content-Length (always last, computed).
    record_id / warcinfo_id: URI with or without surrounding <>; default
    record_id is uuid4().urn. record_date: default now (UTC); a naive datetime
    is assumed to be UTC, see format_warc_date. record_headers:
    {name: value | list/tuple of values | None}; None skips the header, a list
    emits one line per value; values are converted with str().

    Raises ValueError: record_type not a token; content_length not an int in [0, 2**64-1];
    bad header name or value (control characters other than HT); invalid
    record id; a record_headers name equal, case-insensitively, to WARC-Type,
    WARC-Record-ID, WARC-Date, Content-Length or (when warcinfo_id is given)
    WARC-Warcinfo-ID. Nothing is produced on error.
    """
    if not isinstance(record_type, str) or not is_token(record_type):
        raise ValueError("invalid record type: %r" % (record_type,))
    if isinstance(content_length, bool) or not isinstance(content_length, int) or not 0 <= content_length < 2 ** 64:
        raise ValueError("content_length must be an int in [0, 2**64-1]: %r" % (content_length,))
    rid = _clean_uri(uuid4().urn if record_id is None else record_id, "record id")
    wid = None if warcinfo_id is None else _clean_uri(warcinfo_id, "warcinfo id")
    if record_date is None:
        record_date = datetime.now(timezone.utc)

    reserved = _RESERVED + (("warc-warcinfo-id",) if wid is not None else ())
    lines = [
        f"WARC-Type: {record_type}",
        f"WARC-Record-ID: <{rid}>",
    ]
    if wid is not None:
        lines.append(f"WARC-Warcinfo-ID: <{wid}>")
    lines.append(f"WARC-Date: {format_warc_date(record_date)}")
    for name, value in (record_headers or {}).items():
        name = str(name)
        if not is_token(name):
            raise ValueError("invalid header name: %r" % (name,))
        if name.lower() in reserved:
            raise ValueError("header %r is managed by pywarc" % (name,))
        values = value if isinstance(value, (list, tuple)) else (value,)
        for v in values:
            if v is None:
                continue
            v = str(v)
            check_header_value(v)
            lines.append(f"{name}: {v}")
    lines.append(f"Content-Length: {content_length}")
    return ("WARC/1.1\r\n" + "\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def serialize_record(record_type: str, content: bytes, **kwargs) -> bytes:
    """serialize_record_head(record_type, len(content), **kwargs) + content + trailer.

    For small bodies; use iter_serialized_record for large ones.
    """
    return b"".join((serialize_record_head(record_type, len(content), **kwargs), content, _TRAILER))


def iter_serialized_record(record_type: str, content_length: int,
                           body: Union[IO[bytes], Iterable[bytes]], *, chunk_size: int = 64 * 1024,
                           **kwargs) -> Iterator[bytes]:
    """Yield the head, then the body in chunks, then the trailer.

    `body` is a readable binary file object (read in `chunk_size` pieces) or an
    iterable of bytes (empty chunks are skipped). Arguments are validated when
    this function is called (not lazily). While iterating, raises
    ContentLengthMismatchError (before yielding the trailer) if the body has
    more or fewer than `content_length` bytes; an overflowing chunk is not
    yielded. Memory: one chunk at a time. Suitable as a chunked HTTP request body.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    head = serialize_record_head(record_type, content_length, **kwargs)
    return _iter_record(head, content_length, body, chunk_size)


def _iter_record(head: bytes, content_length: int, body, chunk_size: int) -> Iterator[bytes]:
    if isinstance(body, (bytes, bytearray, memoryview)):
        source = iter((body,))  # a bytes-like body is a single chunk
    elif hasattr(body, "read"):
        def chunks():
            while True:
                c = body.read(chunk_size)
                if not c:
                    return
                yield c
        source = chunks()
    else:
        source = iter(body)

    yield head
    total = 0
    for chunk in source:
        if isinstance(chunk, memoryview):
            chunk = bytes(chunk)
        elif not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("body chunks must be bytes-like, got %s" % type(chunk).__name__)
        if not chunk:
            continue
        total += len(chunk)
        if total > content_length:
            raise ContentLengthMismatchError(
                f"body overflows the declared length by {total - content_length} bytes")
        yield chunk
    if total != content_length:
        raise ContentLengthMismatchError(
            f"body has {total} bytes, {content_length} declared")
    yield _TRAILER


class WarcWriter(object):
    def __init__(
        self, file: Union[str, IO[bytes]],
        truncate: bool = False, warc_meta: Optional[dict] = None,
        software_name: str = "unknown", software_version: str = "unkown",
        compress: Optional[bool] = None, uncompress_pos: int = 0,
        *, write_warcinfo: bool = True
    ) -> None:
        # validate the warcinfo payload before opening anything
        encoded_meta = b""
        if write_warcinfo:
            actual_meta = {
                "software": f"{software_name}/{software_version}",
                **DEFAULT_META,
                **(warc_meta or {})}
            encoded_meta = _serialize_dict(actual_meta).encode("utf8")

        if isinstance(file, str):
            self.is_fp_self_managed = True
            self.fp = open(file, "ab" if truncate == False else "wb")
            if compress is None and file.endswith(".gz"):
                compress = True # if compression is not provided and it ends with .gz, then enable it
        else:
            self.is_fp_self_managed = False
            self.fp = file

        if compress:
            self.fp = MakeFakeTellable(SeekableGZipWriter(self.fp))
        else:
            self.fp = MakeFakeTellable(FakeSeekableWriter(self.fp))

        self.uncompress_pos = uncompress_pos
        self.warc_info_id: Optional[str] = uuid4().urn if write_warcinfo else None
        # how many bytes we are waiting to complete the current block
        self.body_remaining_length = 0

        if write_warcinfo:
            self.write_block("warcinfo", encoded_meta, record_id=self.warc_info_id, record_headers={"Content-Type": "application/warc-fields"})

    def write_block(self, record_type: str, content: bytes, **kwargs) -> Tuple[int, int]:
        ret = self.start_block(record_type, len(content), **kwargs)
        self.write_block_body(content)
        return ret

    def start_block(self, record_type: str, content_length: int, record_id: Optional[str] = None,
                    record_date: Optional[datetime] = None,
                    record_headers: Optional[dict] = None) -> Tuple[int, int]:
        if self.body_remaining_length != 0:
            raise PreviousBlockNotTerminatedError(f"previous blocks not terminated: {self.body_remaining_length} bytes missing")

        # validates everything before touching the file
        head = serialize_record_head(
            record_type, content_length, record_id=record_id, record_date=record_date,
            record_headers=record_headers, warcinfo_id=self.warc_info_id)

        uncompress_pos = self.fp.tell()
        compress_pos = self.fp.start_part()

        self.fp.write(head)

        self.body_remaining_length = content_length
        if content_length == 0:
            self.fp.write(_TRAILER)
            self.fp.end_part()

        return (uncompress_pos+self.uncompress_pos, compress_pos)

    def write_block_body(self, content: bytes) -> None:
        if len(content) == 0:
            return
        if self.body_remaining_length < len(content):
            raise CurrentBlockOverflowError(f"current block overflows by {len(content)-self.body_remaining_length} bytes")
        self.fp.write(content)
        self.body_remaining_length -= len(content)
        if self.body_remaining_length == 0:
            self.fp.write(_TRAILER)
            self.fp.end_part()

    def flush(self) -> None:
        self.fp.flush()

    def close(self) -> None:
        self.fp.close()

    def __enter__(self) -> "WarcWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            if getattr(self, "is_fp_self_managed", False) and getattr(self, "fp", None) is not None:
                self.fp.close()
        except Exception:
            pass
