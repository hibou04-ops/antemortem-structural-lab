# Reviewed source extraction; see boltons-LICENSE.txt and manifest.json.
# Copyright (c) 2013 Mahmoud Hashemi
import re
import string

_punct_ws_str = string.punctuation + string.whitespace

_punct_re = re.compile('[' + _punct_ws_str + ']+')

def split_punct_ws(text):
    """While :meth:`str.split` will split on whitespace,
    :func:`split_punct_ws` will split on punctuation and
    whitespace. This used internally by :func:`slugify`, above.

    >>> split_punct_ws('First post! Hi!!!!~1    ')
    ['First', 'post', 'Hi', '1']
    """
    return [w for w in _punct_re.split(text) if w]
