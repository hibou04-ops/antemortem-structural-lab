# Reviewed source extraction; see boltons-LICENSE.txt and manifest.json.
# Copyright (c) 2013 Mahmoud Hashemi
import re

_line_ending_re = re.compile(r'(\r\n|\n|\x0b|\f|\r|\x85|\u2028|\u2029)',
                             re.UNICODE)

def iter_splitlines(text):
    r"""Like :meth:`str.splitlines`, but returns an iterator of lines
    instead of a list. Also similar to :meth:`file.next`, as that also
    lazily reads and yields lines from a file.

    This function works with a variety of line endings, but as always,
    be careful when mixing line endings within a file.

    >>> list(iter_splitlines('\nhi\nbye\n'))
    ['', 'hi', 'bye', '']
    >>> list(iter_splitlines('\r\nhi\rbye\r\n'))
    ['', 'hi', 'bye', '']
    >>> list(iter_splitlines(''))
    []
    """
    prev_end, len_text = 0, len(text)
    # print('last: %r' % last_idx)
    # start, end = None, None
    for match in _line_ending_re.finditer(text):
        start, end = match.start(1), match.end(1)
        # print(start, end)
        if prev_end <= start:
            yield text[prev_end:start]
        if end == len_text:
            yield ''
        prev_end = end
    tail = text[prev_end:]
    if tail:
        yield tail
    return
