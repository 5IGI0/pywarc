# PyWarc

Python library for WebArchive's WARC file format manipulation.

How to read a warc file:
```python
from pywarc import WarcReader

warc = WarcReader("my_archive.warc")
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

How to write a warc file:
```python
from pywarc import WarcWriter
from datetime import datetime
import os

# you can start to write as easy as:
# warc = WarcWriter("my_archive.warc")

# but you have more options:
warc = WarcWriter(
    "my_archive.warc",
    truncate=True, # by default it will appends, but you can choose to truncate it.
    software_name="my_program",
    software_version="1.0.0",
    warc_meta={
        "My-Super-Meta": "Hello, World!", # you can set meta to the warcinfo's block.
        "conformsTo": None})              # or delete default ones with None.

warc.write_block(
    "response",
    b"HTTP/1.1 200 OK\r\nHost: example.com\r\nContent-Type: 0\r\n\r\n",
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
    warc.start_block("my_custom_type", size)
    for l in fp:
        warc.write_block_body(l)
```