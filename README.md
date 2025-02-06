# PyWarc

Python library for WebArchive's WARC file format manipulation.

How to read a warc file:
```python
warc = WarcReader(open("my_archive.warc"))
blk = warc.get_next_block() # read a block

print(blk.content_length) # get content length
print(blk.headers)        # read headers
print(blk.read(10))       # read x bytes
print(blk.read())         # read everything

blk = warc.get_next_block() # read next block
# note that you won't be able to read the previous block anymore
# if the file is not seekable.

print(blk.content_length) # get content length
print(blk.headers)        # read headers

# you can also get the content as a stream
stream = blk.get_as_stream()
print(stream.readline()) # for easier manipulation

# or you can even use a for loop to iterate on each blocks
for blk in warc:
    print(blk.headers["WARC-Record-ID"])
```
