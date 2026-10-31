# Reviewed source extraction; see boltons-LICENSE.txt and manifest.json.
# Copyright (c) 2013 Mahmoud Hashemi

def is_iterable(obj):
    """Similar in nature to :func:`callable`, ``is_iterable`` returns
    ``True`` if an object is `iterable`_, ``False`` if not.

    >>> is_iterable([])
    True
    >>> is_iterable(object())
    False

    .. _iterable: https://docs.python.org/2/glossary.html#term-iterable
    """
    try:
        iter(obj)
    except TypeError:
        return False
    return True

def is_scalar(obj):
    """A near-mirror of :func:`is_iterable`. Returns ``False`` if an
    object is an iterable container type. Strings are considered
    scalar as well, because strings are more often treated as whole
    values as opposed to iterables of 1-character substrings.

    >>> is_scalar(object())
    True
    >>> is_scalar(range(10))
    False
    >>> is_scalar('hello')
    True
    """
    return not is_iterable(obj) or isinstance(obj, (str, bytes))

def split_iter(src, sep=None, maxsplit=None):
    """Splits an iterable based on a separator, *sep*, a max of
    *maxsplit* times (no max by default). *sep* can be:

      * a single value
      * an iterable of separators
      * a single-argument callable that returns True when a separator is
        encountered

    ``split_iter()`` yields lists of non-separator values. A separator will
    never appear in the output.

    >>> list(split_iter(['hi', 'hello', None, None, 'sup', None, 'soap', None]))
    [['hi', 'hello'], ['sup'], ['soap']]

    Note that ``split_iter`` is based on :func:`str.split`, so if
    *sep* is ``None``, ``split()`` **groups** separators. If empty lists
    are desired between two contiguous ``None`` values, simply use
    ``sep=[None]``:

    >>> list(split_iter(['hi', 'hello', None, None, 'sup', None]))
    [['hi', 'hello'], ['sup']]
    >>> list(split_iter(['hi', 'hello', None, None, 'sup', None], sep=[None]))
    [['hi', 'hello'], [], ['sup'], []]

    Using a callable separator:

    >>> falsy_sep = lambda x: not x
    >>> list(split_iter(['hi', 'hello', None, '', 'sup', False], falsy_sep))
    [['hi', 'hello'], [], ['sup'], []]

    See :func:`split` for a list-returning version.

    """
    if not is_iterable(src):
        raise TypeError('expected an iterable')

    if maxsplit is not None:
        maxsplit = int(maxsplit)
        if maxsplit == 0:
            yield [src]
            return

    if callable(sep):
        sep_func = sep
    elif not is_scalar(sep):
        sep = frozenset(sep)
        def sep_func(x): return x in sep
    else:
        def sep_func(x): return x == sep

    cur_group = []
    split_count = 0
    for s in src:
        if maxsplit is not None and split_count >= maxsplit:
            def sep_func(x): return False
        if sep_func(s):
            if sep is None and not cur_group:
                # If sep is none, str.split() "groups" separators
                # check the str.split() docs for more info
                continue
            split_count += 1
            yield cur_group
            cur_group = []
        else:
            cur_group.append(s)

    if cur_group or sep is not None:
        yield cur_group
    return
