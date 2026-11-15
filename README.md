# PyWarc

Python library for WebArchive's WARC file format manipulation.

How to read a warc file:
```python
from pywarc import WarcReader


# if the suffix .gz is present, then it will decompress
# but you can also overwrite it with compressed=True or compressed=False
warc = WarcReader("my_archive.warc.gz")
# you can also provide your own fp
# warc = WarcReader(sys.stdin.buffer)
blk = warc.get_next_block() # read a block

print(blk.content_length) # get content length
print(blk.headers)        # read headers
print(blk.read(10))       # read x bytes
print(blk.read())         # read every next bytes

blk = warc.get_next_block() # read next block
# note that you won't be able to read the previous block anymore
# if the file is not seekable.

print(blk.content_length) # get content length
# read WARC headers
print(blk.type)
print(blk.date) # will return a datetime
print(blk.content_type) # str or None
print(blk.record_id)
print(blk.warcinfo_id)

# you can also get the content as a stream
stream = blk.get_as_stream() # NOTE: it will read the whole block, do not do that to read big files
print(stream.readline()) # for easier manipulation

# or you can even use a for loop to iterate on each blocks
for blk in warc:
    print(blk.record_id)
```

Header access (names are case-insensitive, repeated headers are supported):
```python
blk.header("Content-Type")           # first value or None (or a default: blk.header("X", "dflt"))
blk.header_all("WARC-Concurrent-To") # list of every value, in record order
blk.headers                          # {name as written: [values]}
blk.version                          # "WARC/1.0" or "WARC/1.1"
blk.target_uri, blk.payload_digest, blk.block_digest
blk.refers_to, blk.concurrent_to     # <> stripped; concurrent_to is a list
```

Readers are context managers (`with WarcReader(path) as warc:`); `close()` closes
what the reader opened itself (never a stream you passed in). Both `WARC/1.0` and
`WARC/1.1` records are read. The reader is strict: truncated input raises
`TruncatedWarcError` (a subclass of `InvalidWarcError`), other malformed input
`InvalidWarcError`; the head is bounded by `max_header_bytes` (default 64 KiB)
and `max_headers` (default 1024), and the `\r\n\r\n` record trailer is checked.

Parse a single record held in memory, or stream one from a non-seekable source
such as an HTTP response (the body is never buffered by the reader):
```python
from pywarc import parse_record, WarcReader

blk = parse_record(data)  # exactly one uncompressed record, else InvalidWarcError

blk = WarcReader(response).get_next_block()   # e.g. http.client.HTTPResponse
while True:
    chunk = blk.read(65536)
    if not chunk:
        break
    ...
```

Dates: `blk.date` is always a timezone-aware UTC `datetime`. All WARC profiles are
accepted (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or a time part with `Z`/`+hh:mm`);
a time without a time zone designator raises `WarcHeaderBadValueError`.
`format_warc_date(d)` writes `YYYY-MM-DDThh:mm:ssZ` (naive datetimes are assumed
to be UTC, aware ones are converted).

How to write a warc file:
```python
from pywarc import WarcWriter
from datetime import datetime
import os

# you can start to write as easy as:
# warc = WarcWriter("my_archive.warc")

# but you have more options:
warc = WarcWriter(
    # if the suffix .gz is present, then it will compress
    # but you can also overwrite it with compress=True or compress=False
    "my_archive.warc",
    truncate=True, # by default it will appends, but you can choose to truncate it.
    software_name="my_program",
    software_version="1.0.0",
    warc_meta={
        "My-Super-Meta": "Hello, World!", # you can set meta to the warcinfo's block.
        "conformsTo": None})              # or delete default ones with None.

# returns a tuple: (<uncompressed_pos>,<compressed_pos>)
#
# compressed_pos can be used to seek before opening it with reader
# to retrieve the wanted record without uncompressing previous records.
#
# NOTE: uncompressed_pos is per instance, so if you open in append mode, it will be relative from this location.
# if you know the current position before opening, you can use uncompress_pos=... in the constructor
warc.write_block(
    "response",
    b"HTTP/1.1 200 OK\r\nHost: example.com\r\nContent-Length: 0\r\n\r\n",
    # optional fields:
    record_date=datetime.fromisocalendar(2000, 1, 1), # by default it will be set to the current UTC time.
    record_id="urn:custom:i_dont_know", # your record identifier, NOTE: it _must_ be a valid URI. (default: uuid.uuid4().urn)
    record_headers={"Content-Type": "application/http;msgtype=response"})

# if your object is too big to be in memory
# you can write it in several calls:

with open("hypothetical_file.txt", "rb") as fp:
    size = fp.seek(0, os.SEEK_END)
    fp.seek(0, os.SEEK_SET)

    # please note that this implies that if an error occurs at this point,
    # the archive will be truncated and so if you reopen this file for writing,
    # all subsequent data will be corrupted.
    warc.start_block("my_custom_type", size) # returns the same values as write_block()
    for l in fp:
        warc.write_block_body(l)
```

Writer options and context manager:
```python
# no warcinfo record (and no WARC-Warcinfo-ID header on records)
with WarcWriter("my_archive.warc", write_warcinfo=False) as warc:
    warc.write_block("resource", b"data")
```
`record_id` / `record_headers` are validated (`ValueError`) before anything is
written. `record_headers` values may be a string, a list/tuple (one line per
value) or `None` (skipped). `record_id` may be given with or without `<>`.
Naive `record_date` values are assumed to be UTC.

Serialize a single record without a file (always WARC/1.1, no warcinfo):
```python
from pywarc import serialize_record, serialize_record_head, iter_serialized_record

data = serialize_record("resource", b"abc", record_id="urn:x:1",
                        record_headers={"WARC-Target-URI": "http://e.x/"})

# large bodies: stream head, body chunks and trailer (e.g. as a chunked HTTP
# request body). Raises ContentLengthMismatchError if the body length differs.
with open("big.bin", "rb") as fp:
    for chunk in iter_serialized_record("resource", size, fp, chunk_size=65536):
        send(chunk)
```
`WARC-Type`, `WARC-Record-ID`, `WARC-Date` and `Content-Length` are managed and
cannot be given in `record_headers`.

## Tests

```sh
python3 -m unittest   # from the repository root
```

Byte-exact re-send (keeps `WARC/1.0`, odd spacing, folded lines): `blk.raw_head` is
the record head exactly as read, and `blk.iter_raw(chunk_size=65536)` yields
`raw_head`, the body in chunks, then the canonical `\r\n\r\n` trailer (the record's
real trailer is validated by the next `get_next_block()`). It re-reads the body from
its start: on a non-seekable input it raises `NotSeekableError` if the body was
already partly read.

Performance: sequential reads are linear on seekable and non-seekable inputs,
and unread bodies of a plain seekable file are skipped with one `seek`. On a `.gz`
input, reading an earlier block re-decompresses from the start; read bodies in
order for linear time (this includes `iter_raw`, or `read(n)` after a partial read
on an earlier block: each such chunk re-decompresses from the start).
A cut or corrupted gzip member raises `TruncatedWarcError` / `InvalidWarcError`
(the original exception is the `__cause__`).

## Changes in 0.4.1

- New `WarcBlock.raw_head` and `WarcBlock.iter_raw()` (byte-exact re-emit).
- Fixed quadratic time when reading bodies of a seekable gzip input (no more seek
  per `read()`), and skipping unread bodies of a plain seekable file is O(1).

## Changes in 0.4.0

New: `parse_record`, `serialize_record`, `serialize_record_head`,
`iter_serialized_record`, `parse_warc_date`, `format_warc_date`, `WarcBlock.header`,
`header_all`, `version`, `target_uri`, `payload_digest`, `block_digest`,
`refers_to`, `concurrent_to`, `TruncatedWarcError`, `ContentLengthMismatchError`,
`write_warcinfo=False`, context managers, `max_header_bytes` / `max_headers`,
non-seekable streams without a `seekable()` method. `python_requires>=3.7` is now true.

Behaviour changes (bug fixes):
- repeated headers give lists of all values (were `None` / crash on the third);
- header names are case-insensitive in getters and `header()`; `blk.headers` keeps names as written;
- `Name:value` (no space), surrounding whitespace and folded lines are accepted;
  values are stripped of leading/trailing SP/HT;
- `WARC/1.0` records are readable;
- non-canonical, negative or duplicate `Content-Length`, invalid UTF-8 headers,
  oversize heads, missing trailers and truncated records raise
  `InvalidWarcError` / `TruncatedWarcError` instead of yielding garbage or short reads;
- `blk.date` is always tz-aware UTC; a time without a TZD raises `WarcHeaderBadValueError`
  (before: naive datetime on 3.11, crash before 3.11 for `Z`);
- writer: aware datetimes are converted to UTC (was an invalid `+00:00Z`);
  `record_headers` duplicating a managed header or containing CR/LF/control
  characters raise `ValueError` (before: invalid output / header injection);
  `warc_meta` values are checked too;
- a garbage-collected compressed `WarcWriter` no longer closes the caller's file;
- the raw file of a `.gz` path opened by `WarcReader` is closed.
- `record_id` / `warcinfo_id` are validated: an id without `:`, or containing a
  space, `<` or `>`, raises `ValueError` (0.3.x accepted anything); `"<x>"` no
  longer becomes `<<x>>`;
- `record_type` must be an RFC 9110 token (`"my type"` raises `ValueError`);
- list/tuple values in `record_headers` emit one line per value (0.3.x wrote `str(list)`);
- `content_length` must be an `int` in `[0, 2**64-1]` (no bool, float or numpy int);
- the `WarcReader.next_block` attribute is gone (internal state is now private);
- a version line cut by EOF raises `TruncatedWarcError`.

Strictness notes: the reader accepts control bytes in header values, but the
writer rejects them. `concurrent_to` is lenient about `<>` (stripped if present)
while `refers_to`, `record_id` and `warcinfo_id` require them.

Masstuffy server limits that matter for clients: at most 256 headers, 64 KiB of
headers and (by default) 1 GiB of body per record. The writer does not enforce
them; the reader's defaults are `max_headers=1024`, `max_header_bytes=64 KiB`.
