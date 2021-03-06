from __future__ import absolute_import, print_function, division
import os.path
import re
import codecs
import unicodedata
import importlib
import inspect

import six


def always_bytes(unicode_or_bytes, *encode_args):
    if isinstance(unicode_or_bytes, six.text_type):
        return unicode_or_bytes.encode(*encode_args)
    return unicode_or_bytes


def native(s, *encoding_opts):
    """
    Convert :py:class:`bytes` or :py:class:`unicode` to the native
    :py:class:`str` type, using latin1 encoding if conversion is necessary.

    https://www.python.org/dev/peps/pep-3333/#a-note-on-string-types
    """
    if not isinstance(s, (six.binary_type, six.text_type)):
        raise TypeError("%r is neither bytes nor unicode" % s)
    if six.PY3:
        if isinstance(s, six.binary_type):
            return s.decode(*encoding_opts)
    else:
        if isinstance(s, six.text_type):
            return s.encode(*encoding_opts)
    return s


def clean_bin(s, keep_spacing=True):
    """
        Cleans binary data to make it safe to display.

        Args:
            keep_spacing: If False, tabs and newlines will also be replaced.
    """
    if isinstance(s, six.text_type):
        if keep_spacing:
            keep = u" \n\r\t"
        else:
            keep = u" "
        return u"".join(
            ch if (unicodedata.category(ch)[0] not in "CZ" or ch in keep) else u"."
            for ch in s
        )
    else:
        if keep_spacing:
            keep = (9, 10, 13)  # \t, \n, \r,
        else:
            keep = ()
        return b"".join(
            six.int2byte(ch) if (31 < ch < 127 or ch in keep) else b"."
            for ch in six.iterbytes(s)
        )


def hexdump(s):
    """
        Returns:
            A generator of (offset, hex, str) tuples
    """
    for i in range(0, len(s), 16):
        offset = "{:0=10x}".format(i).encode()
        part = s[i:i + 16]
        x = b" ".join("{:0=2x}".format(i).encode() for i in six.iterbytes(part))
        x = x.ljust(47)  # 16*2 + 15
        yield (offset, x, clean_bin(part, False))


def setbit(byte, offset, value):
    """
        Set a bit in a byte to 1 if value is truthy, 0 if not.
    """
    if value:
        return byte | (1 << offset)
    else:
        return byte & ~(1 << offset)


def getbit(byte, offset):
    mask = 1 << offset
    return bool(byte & mask)


class BiDi(object):

    """
        A wee utility class for keeping bi-directional mappings, like field
        constants in protocols. Names are attributes on the object, dict-like
        access maps values to names:

        CONST = BiDi(a=1, b=2)
        assert CONST.a == 1
        assert CONST.get_name(1) == "a"
    """

    def __init__(self, **kwargs):
        self.names = kwargs
        self.values = {}
        for k, v in kwargs.items():
            self.values[v] = k
        if len(self.names) != len(self.values):
            raise ValueError("Duplicate values not allowed.")

    def __getattr__(self, k):
        if k in self.names:
            return self.names[k]
        raise AttributeError("No such attribute: %s", k)

    def get_name(self, n, default=None):
        return self.values.get(n, default)


class Data(object):

    def __init__(self, name):
        m = importlib.import_module(name)
        dirname = os.path.dirname(inspect.getsourcefile(m))
        self.dirname = os.path.abspath(dirname)

    def path(self, path):
        """
            Returns a path to the package data housed at 'path' under this
            module.Path can be a path to a file, or to a directory.

            This function will raise ValueError if the path does not exist.
        """
        fullpath = os.path.join(self.dirname, path)
        if not os.path.exists(fullpath):
            raise ValueError("dataPath: %s does not exist." % fullpath)
        return fullpath


_label_valid = re.compile(b"(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)


def is_valid_host(host):
    """
    Checks if a hostname is valid.

    Args:
      host (bytes): The hostname
    """
    try:
        host.decode("idna")
    except ValueError:
        return False
    if len(host) > 255:
        return False
    if host[-1] == b".":
        host = host[:-1]
    return all(_label_valid.match(x) for x in host.split(b"."))


def is_valid_port(port):
    return 0 <= port <= 65535


def hostport(scheme, host, port):
    """
        Returns the host component, with a port specifcation if needed.
    """
    if (port, scheme) in [(80, "http"), (443, "https"), (80, b"http"), (443, b"https")]:
        return host
    else:
        if isinstance(host, six.binary_type):
            return b"%s:%d" % (host, port)
        else:
            return "%s:%d" % (host, port)


def safe_subn(pattern, repl, target, *args, **kwargs):
    """
        There are Unicode conversion problems with re.subn. We try to smooth
        that over by casting the pattern and replacement to strings. We really
        need a better solution that is aware of the actual content ecoding.
    """
    return re.subn(str(pattern), str(repl), target, *args, **kwargs)


def bytes_to_escaped_str(data):
    """
    Take bytes and return a safe string that can be displayed to the user.

    Single quotes are always escaped, double quotes are never escaped:
        "'" + bytes_to_escaped_str(...) + "'"
    gives a valid Python string.
    """
    # TODO: We may want to support multi-byte characters without escaping them.
    # One way to do would be calling .decode("utf8", "backslashreplace") first
    # and then escaping UTF8 control chars (see clean_bin).

    if not isinstance(data, bytes):
        raise ValueError("data must be bytes, but is {}".format(data.__class__.__name__))
    # We always insert a double-quote here so that we get a single-quoted string back
    # https://stackoverflow.com/questions/29019340/why-does-python-use-different-quotes-for-representing-strings-depending-on-their
    return repr(b'"' + data).lstrip("b")[2:-1]


def escaped_str_to_bytes(data):
    """
    Take an escaped string and return the unescaped bytes equivalent.
    """
    if not isinstance(data, six.string_types):
        if six.PY2:
            raise ValueError("data must be str or unicode, but is {}".format(data.__class__.__name__))
        raise ValueError("data must be str, but is {}".format(data.__class__.__name__))

    if six.PY2:
        if isinstance(data, unicode):
            data = data.encode("utf8")
        return data.decode("string-escape")

    # This one is difficult - we use an undocumented Python API here
    # as per http://stackoverflow.com/a/23151714/934719
    return codecs.escape_decode(data)[0]
