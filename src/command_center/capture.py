"""Route overlapping plugin calls to separate Python output buffers."""

from contextlib import contextmanager
from io import StringIO
import sys
from threading import RLock, local


class Buffer(StringIO):
    def close(self):
        pass


class Stream:
    def __init__(self, default):
        self.default = default
        self.local = local()
        self.users = 0

    def __getattr__(self, key):
        return getattr(getattr(self.local, "buffer", self.default), key)


_lock = RLock()


@contextmanager
def capture(name):
    with _lock:
        stream = getattr(sys, name)
        if not isinstance(stream, Stream):
            stream = Stream(stream)
            setattr(sys, name, stream)
        previous = getattr(stream.local, "buffer", None)
        stream.local.buffer = buffer = Buffer()
        stream.users += 1
    try:
        yield buffer
    finally:
        with _lock:
            if previous is None:
                del stream.local.buffer
            else:
                stream.local.buffer = previous
            stream.users -= 1
            if not stream.users and getattr(sys, name) is stream:
                setattr(sys, name, stream.default)
