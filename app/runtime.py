"""Use a psycopg-compatible event loop on Windows for the native API."""
import asyncio
import sys


def selector_loop_factory(use_subprocess: bool = False):
    return asyncio.SelectorEventLoop() if sys.platform == 'win32' else asyncio.new_event_loop()
