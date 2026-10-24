"""Serialize financial transitions within the supported single-worker demo."""
import asyncio
from functools import wraps
from weakref import WeakKeyDictionary

_locks = WeakKeyDictionary()

def serialized(function):
    @wraps(function)
    async def guarded(*args, **kwargs):
        loop = asyncio.get_running_loop()
        lock = _locks.setdefault(loop, asyncio.Lock())
        async with lock:
            return await function(*args, **kwargs)
    return guarded
