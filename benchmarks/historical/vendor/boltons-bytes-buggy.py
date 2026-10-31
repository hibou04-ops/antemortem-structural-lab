# Reviewed source extraction; see boltons-LICENSE.txt and manifest.json.
# Copyright (c) 2013 Mahmoud Hashemi
import math

_SIZE_SYMBOLS = ('B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')

_SIZE_BOUNDS = [(1024 ** i, sym) for i, sym in enumerate(_SIZE_SYMBOLS)]

_SIZE_BOUNDS.append((float('inf'), ''))

_SIZE_RANGES = list(zip(_SIZE_BOUNDS, _SIZE_BOUNDS[1:]))

def bytes2human(nbytes, ndigits=0):
    """Turns an integer value of *nbytes* into a human readable format. Set
    *ndigits* to control how many digits after the decimal point
    should be shown (default ``0``).

    >>> bytes2human(128991)
    '126K'
    >>> bytes2human(100001221)
    '95M'
    >>> bytes2human(0, 2)
    '0.00B'
    >>> bytes2human(1024)
    '1K'
    >>> bytes2human(1024 ** 8)
    '1Y'
    """
    abs_bytes = abs(nbytes)
    for (size, symbol), (next_size, next_symbol) in _SIZE_RANGES:
        if abs_bytes < next_size:
            break
    hnbytes = float(nbytes) / size
    return '{hnbytes:.{ndigits}f}{symbol}'.format(hnbytes=hnbytes,
                                                  ndigits=ndigits,
                                                  symbol=symbol)
