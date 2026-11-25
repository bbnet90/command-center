"""Textual workers that can abandon a blocked synchronous call on shutdown."""
import asyncio
from contextvars import copy_context
from functools import wraps
from threading import Thread

from textual import work


def background(function):
    @wraps(function)
    async def invoke(*args, **kwargs):
        loop = asyncio.get_running_loop()
        result = loop.create_future()

        def complete(value, error):
            if not result.done():
                if error is None:
                    result.set_result(value)
                else:
                    result.set_exception(error)

        def call():
            try:
                value = function(*args, **kwargs)
            except BaseException as exc:
                value, error = None, exc
            else:
                error = None
            try:
                loop.call_soon_threadsafe(complete, value, error)
            except RuntimeError:
                pass  # The application already closed its event loop.

        Thread(target=copy_context().run, args=(call,), daemon=True).start()
        return await result

    return work(exit_on_error=False)(invoke)
