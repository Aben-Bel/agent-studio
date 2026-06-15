import time, functools, logging, contextlib

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("jokeplatform")


def retry(attempts=3, base=0.4, exceptions=(Exception,)):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            last = None
            for i in range(attempts):
                try:
                    return fn(*a, **k)
                except exceptions as e:
                    last = e
                    log.warning("retry %d/%d %s: %s", i + 1, attempts, fn.__name__, e)
                    time.sleep(base * (2 ** i))
            raise last
        return wrap
    return deco


@contextlib.contextmanager
def trace(event, **meta):
    t = time.time()
    log.info("-> %s %s", event, meta)
    try:
        yield
    finally:
        log.info("<- %s %.3fs", event, time.time() - t)
