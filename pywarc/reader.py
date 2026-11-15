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

import gzip
import zlib
from datetime import datetime
from io import BytesIO
from typing import IO, Callable, Dict, Iterator, List, Optional, Union

from ._headers import is_token, parse_content_length, parse_warc_date, strip_brackets
from .errors import (  # noqa: F401  (re-exported for backward compatibility)
    InvalidWarcError,
    MissingWarcHeaderError,
    NotSeekableError,
    TruncatedWarcError,
    WarcHeaderBadValueError,
)

MAX_SKIPBUF = 4096
DEFAULT_MAX_HEADER_BYTES = 64 * 1024
DEFAULT_MAX_HEADERS = 1024

_VERSIONS = {b"WARC/1.0\r\n": "WARC/1.0", b"WARC/1.1\r\n": "WARC/1.1"}
_TRAILER = b"\r\n\r\n"
# errors raised by GzipFile on corrupted compressed data (BadGzipFile: 3.8+,
# earlier versions raise OSError which cannot be told from real I/O errors)
_GZIP_CORRUPT = (zlib.error,) + ((gzip.BadGzipFile,) if hasattr(gzip, "BadGzipFile") else ())


def _url_header_sanitizer(header: str) -> str:
    if len(header) < 2 or header[0] != "<" or header[-1] != ">":
        raise ValueError("expected a value between '<' and '>'")
    return header[1:-1]


def _get_header(header: str, is_mandatory: bool, sanitize: Callable[[str], object] = str):
    def header_getter(self):
        val = self.header(header)
        if val is None:
            if is_mandatory:
                raise MissingWarcHeaderError(f"header '{header}' not present")
            return None
        try:
            return sanitize(val)
        except Exception as e:
            raise WarcHeaderBadValueError(f"'{header}' contains an invalid value") from e
    return header_getter


def _concurrent_to(self) -> List[str]:
    return [strip_brackets(v) for v in self.header_all("WARC-Concurrent-To")]


class WarcBlock(object):
    """One WARC record: its headers and a lazy view on its body."""

    def __init__(self, warc_reader: "WarcReader", headers: Dict[str, List[str]],
                 block_content_pos: int, version: str = "WARC/1.1",
                 lower: Optional[Dict[str, List[str]]] = None,
                 raw_head: Optional[bytes] = None) -> None:
        self.warc_reader = warc_reader
        self.block_content_pos = block_content_pos
        self.read_offset = 0
        self.headers = headers
        self.version = version
        self.raw_head = raw_head  # head bytes exactly as read (version line .. blank line)
        if lower is None:
            lower = {}
            for k, vs in headers.items():
                lower.setdefault(k.lower(), []).extend(vs)
        self._lower: Dict[str, List[str]] = lower
        cl = self.header("Content-Length")
        if cl is None:
            raise InvalidWarcError("current record doesn't have 'Content-Length' header")
        self.content_length = parse_content_length(cl)

    def header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """First value of header `name` (case-insensitive), or `default`."""
        vs = self._lower.get(name.lower())
        return vs[0] if vs else default

    def header_all(self, name: str) -> List[str]:
        """All values of header `name` in record order (case-insensitive); [] if absent."""
        return list(self._lower.get(name.lower(), ()))

    def read(self, nread: Optional[int] = None) -> bytes:
        """Read up to `nread` body bytes (all remaining if None).

        Raises TruncatedWarcError if the input ends before the declared body does.
        """
        unread_data = self.content_length - self.read_offset

        if nread is None or nread < 0 or nread > unread_data:
            nread = unread_data

        ret = self.warc_reader.read_at(nread, self.block_content_pos + self.read_offset)
        self.read_offset += len(ret)
        if len(ret) < nread:
            raise TruncatedWarcError("record body is truncated")
        return ret

    def iter_raw(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Yield the record byte-exactly as read: raw_head, the body in chunks
        of at most `chunk_size`, then b"\\r\\n\\r\\n".

        Re-reads the body from its start (resets read_offset to 0): on a
        non-seekable input this raises NotSeekableError if the body was already
        partly read or the reader moved past it. Raises ValueError (at call
        time) if raw_head is None or chunk_size < 1, and TruncatedWarcError if
        the body is cut. The trailer is the canonical one; the actual trailer
        of this record is validated by the next get_next_block() call.
        """
        if self.raw_head is None:
            raise ValueError("raw_head is not available for this block")
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        reader = self.warc_reader
        if not reader.is_seekable and reader.current_pos != self.block_content_pos:
            # fail before anything is yielded: never emit a lone head
            raise NotSeekableError("body already partly read on a non-seekable input")
        return self._iter_raw(chunk_size)

    def _iter_raw(self, chunk_size: int) -> Iterator[bytes]:
        self.read_offset = 0
        yield self.raw_head
        while True:
            chunk = self.read(chunk_size)
            if not chunk:
                break
            yield chunk
        yield _TRAILER

    def get_as_stream(self) -> BytesIO:
        """The whole body as a BytesIO (slurps the body)."""
        ret = self.warc_reader.read_at(self.content_length, self.block_content_pos)
        if len(ret) < self.content_length:
            raise TruncatedWarcError("record body is truncated")
        return BytesIO(ret)

    type = property(_get_header("WARC-Type", True))
    date = property(_get_header("WARC-Date", True, parse_warc_date))
    content_type = property(_get_header("Content-Type", False))
    record_id = property(_get_header("WARC-Record-ID", True, _url_header_sanitizer))
    warcinfo_id = property(_get_header("WARC-Warcinfo-ID", False, _url_header_sanitizer))
    target_uri = property(_get_header("WARC-Target-URI", False, strip_brackets))
    payload_digest = property(_get_header("WARC-Payload-Digest", False))
    block_digest = property(_get_header("WARC-Block-Digest", False))
    refers_to = property(_get_header("WARC-Refers-To", False, _url_header_sanitizer))
    concurrent_to = property(_concurrent_to)


class WarcReader(object):
    """Reads WARC/1.0 and WARC/1.1 records from a path or a binary stream.

    The stream may be non-seekable (e.g. an HTTP response); then only the
    current record can be read. `close()` closes what the reader opened itself
    (the file opened from a path and the gzip wrapper), never a stream you
    passed in.
    """

    def __init__(self, file: Union[str, IO[bytes]], compressed: Optional[bool] = None,
                 *, max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
                 max_headers: int = DEFAULT_MAX_HEADERS) -> None:
        self.fp = None
        self._raw_fp = None
        self._gzip_fp = None
        self.max_header_bytes = max_header_bytes
        self.max_headers = max_headers
        if isinstance(file, str):
            self.is_fp_self_managed = True
            self._raw_fp = open(file, "rb")
            raw = self._raw_fp
            if compressed is None and file.endswith(".gz"):
                compressed = True
        else:
            self.is_fp_self_managed = False
            raw = file
        self.fp = raw

        # Gzip python API assume the underlying file is seekable
        # So we need to check the seekableness before sending it to gzip
        try:
            self.is_seekable = bool(getattr(raw, "seekable", lambda: False)())
            if compressed:
                self._gzip_fp = gzip.GzipFile(fileobj=raw)
                self.fp = self._gzip_fp

            self.current_pos = self.fp.tell() if self.is_seekable else 0
        except BaseException:
            self.close()
            raise
        self._prev_body_end: Optional[int] = None

    # internal I/O (all of them keep current_pos in sync with the stream)

    def _fp_call(self, name: str, *args):
        """Call fp.<name>, mapping gzip failures to pywarc errors."""
        try:
            return getattr(self.fp, name)(*args)
        except EOFError as e:  # GzipFile: compressed member cut
            raise TruncatedWarcError("compressed input is truncated") from e
        except _GZIP_CORRUPT as e:
            raise InvalidWarcError(f"corrupted compressed input: {e}") from e

    def _readline(self, limit: int) -> bytes:
        line = self._fp_call("readline", limit)
        self.current_pos += len(line)
        return line

    def _read_n(self, nread: int, advance: bool = False) -> bytes:
        """Read up to nread bytes (short only at EOF). With `advance`,
        current_pos follows every chunk actually read, even if a later read raises."""
        chunks = []
        got = 0
        while got < nread:
            chunk = self._fp_call("read", nread - got)
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
            if advance:
                self.current_pos += len(chunk)
        return chunks[0] if len(chunks) == 1 else b"".join(chunks)

    def _read_exact(self, n: int) -> bytes:
        return self._read_n(n, True)

    def get_next_block(self) -> Optional[WarcBlock]:
        """Return the next record, or None at a clean end of input.

        Raises InvalidWarcError (malformed) or TruncatedWarcError (cut input).
        """
        if self._prev_body_end is not None:
            self.skip_to(self._prev_body_end)
            trailer = self._read_exact(4)
            if len(trailer) < 4:
                raise TruncatedWarcError("record trailer is truncated")
            if trailer != _TRAILER:
                raise InvalidWarcError("missing record trailer")
            self._prev_body_end = None

        limit = self.max_header_bytes
        line = self._readline(limit + 1)
        if line == b"":
            return None
        if line not in _VERSIONS:
            if not line.endswith(b"\n") and any(v.startswith(line) for v in _VERSIONS):
                raise TruncatedWarcError("record version line is truncated")
            raise InvalidWarcError(f"invalid WARC header: {line[:64]!r}")
        version = _VERSIONS[line]
        used = len(line)
        head_parts = [line]

        entries: List[List[bytes]] = []
        while True:
            remaining = limit - used
            line = self._readline(remaining + 1)
            if len(line) > remaining:
                raise InvalidWarcError("header section too large")
            used += len(line)
            head_parts.append(line)
            if not line.endswith(b"\n"):
                raise TruncatedWarcError("record head is truncated")
            if not line.endswith(b"\r\n"):
                raise InvalidWarcError("header line not terminated by CRLF")
            if line == b"\r\n":
                break
            line = line[:-2]
            if line.startswith((b" ", b"\t")):
                if not entries:
                    raise InvalidWarcError("continuation line without a header")
                prev = entries[-1][1]
                cont = line.strip(b" \t")
                entries[-1][1] = (prev + b" " + cont) if prev.strip(b" \t") else cont
                continue
            name, sep, value = line.partition(b":")
            if not sep:
                raise InvalidWarcError(f"invalid WARC header: {line[:64]!r}")
            if len(entries) >= self.max_headers:
                raise InvalidWarcError("too many headers")
            entries.append([name, value])

        headers: Dict[str, List[str]] = {}
        lower: Dict[str, List[str]] = {}
        for name_b, value_b in entries:
            try:
                name = name_b.decode("ascii")
            except UnicodeDecodeError as e:
                raise InvalidWarcError(f"invalid header name: {name_b[:64]!r}") from e
            if not is_token(name):
                raise InvalidWarcError(f"invalid header name: {name!r}")
            try:
                value = value_b.strip(b" \t").decode("utf-8")
            except UnicodeDecodeError as e:
                raise InvalidWarcError(f"header '{name}' is not valid UTF-8") from e
            headers.setdefault(name, []).append(value)
            lower.setdefault(name.lower(), []).append(value)

        block = WarcBlock(self, headers, self.current_pos, version, lower, b"".join(head_parts))
        if len(block.header_all("Content-Length")) > 1:
            raise InvalidWarcError("duplicate Content-Length")
        self._prev_body_end = self.current_pos + block.content_length
        return block

    def skip_to(self, at: int) -> None:
        if at == self.current_pos:
            return
        if at < self.current_pos:
            raise NotSeekableError("file not seekable (you can't read previous blocks once readed/skipped)")

        if self.is_seekable and self._gzip_fp is None:
            # plain seekable file: O(1) skip; a short file is detected by the
            # trailer read that follows
            self._fp_call("seek", at)
            self.current_pos = at
            return

        while self.current_pos < at:
            chunk = self._fp_call("read", min(MAX_SKIPBUF, at - self.current_pos))
            if not chunk:
                raise TruncatedWarcError("input ended while skipping a record body")
            self.current_pos += len(chunk)

    def read_at(self, nread: int, at: int) -> bytes:
        if at != self.current_pos:
            if not self.is_seekable or (self._gzip_fp is not None and at > self.current_pos):
                # forward-only: never seek (raises NotSeekableError going back
                # on a non-seekable input)
                self.skip_to(at)
            else:
                # random access to an earlier block (on gzip this rewinds and
                # re-decompresses from the start)
                self._fp_call("seek", at)
                try:
                    return self._read_n(nread)
                finally:
                    self._fp_call("seek", self.current_pos)
        return self._read_n(nread, True)

    def close(self) -> None:
        """Close the gzip wrapper and the file opened from a path (idempotent)."""
        gz = getattr(self, "_gzip_fp", None)
        if gz is not None:
            self._gzip_fp = None
            gz.close()
        raw = getattr(self, "_raw_fp", None)
        if raw is not None:
            self._raw_fp = None
            raw.close()

    # Magic Methods

    def __next__(self) -> WarcBlock:
        ret = self.get_next_block()
        if ret is None:
            raise StopIteration
        return ret

    def __iter__(self) -> "WarcReader":
        return self

    def __enter__(self) -> "WarcReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            if getattr(self, "is_fp_self_managed", False):
                self.close()
        except Exception:
            pass


def parse_record(data: bytes, *, max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
                 max_headers: int = DEFAULT_MAX_HEADERS) -> WarcBlock:
    """Parse exactly one (uncompressed) WARC record from `data`.

    Raises InvalidWarcError on malformed input ("empty input" on b"",
    "trailing data" if bytes follow the trailer) and TruncatedWarcError if
    the record is incomplete. The block reads from an internal BytesIO.
    For streams, use `WarcReader(stream).get_next_block()` and `block.read(n)`.
    """
    reader = WarcReader(BytesIO(data), compressed=False,
                        max_header_bytes=max_header_bytes, max_headers=max_headers)
    block = reader.get_next_block()
    if block is None:
        raise InvalidWarcError("empty input")
    end = block.block_content_pos + block.content_length
    tail = bytes(data[end:end + 5])
    if len(tail) < 4:
        raise TruncatedWarcError("record is truncated")
    if tail[:4] != _TRAILER:
        raise InvalidWarcError("missing record trailer")
    if len(tail) > 4:
        raise InvalidWarcError("trailing data")
    return block
