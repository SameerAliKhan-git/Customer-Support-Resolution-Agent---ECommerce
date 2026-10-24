"""Per-invocation measurements. No customer messages, prompts or tokens are recorded."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import time

current=ContextVar('support_metrics',default=None)

@contextmanager
def measure(previous=None):
    counters=dict(previous or {})
    for key in ('tool_calls','model_calls','input_tokens','output_tokens','provider_calls','active_seconds'):
        counters.setdefault(key,0)
    token=current.set(counters)
    start=time.perf_counter()
    try:yield counters
    finally:
        counters['active_seconds']+=round(time.perf_counter()-start,6)
        current.reset(token)

def add(key,amount=1):
    counters=current.get()
    if counters is not None:counters[key]=counters.get(key,0)+amount

def tool(function):
    @wraps(function)
    async def measured(*args,**kwargs):
        add('tool_calls')
        return await function(*args,**kwargs)
    return measured
