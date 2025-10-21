import asyncio

async def wait_for_condition(predicate, *, timeout=0.5, interval=0.002, fail_msg="condition not met"):
    """Poll predicate until True or timeout; raises AssertionError on failure.
    Designed to replace arbitrary sleeps in tests for speed and determinism.
    """
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= end:
            raise AssertionError(fail_msg)
        await asyncio.sleep(interval)
