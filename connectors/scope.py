"""Per-run data scope — enforces the user's source/document selection at the
connector layer, where ALL data access funnels through (datastore.list_sources /
run_sql, memory.list_documents / search).

Why here and not in each tool: ~14 tools read the datastore/memory directly. Filtering
in every one would leak the moment someone adds a 15th. Enforcing at the four connector
chokepoints means a deselected table/document is physically invisible to every tool and
every agent — the model cannot query what it cannot see, regardless of the prompt.

Semantics (this is the contract the UI's selection maps onto):
  * scope unset (None)        -> everything visible (no selection made = use all).
  * scope set to a list       -> ONLY those names visible. The list mixes SQL source
                                 names, table names, and document names (the UI sends a
                                 flat list); each access checks membership for its kind.
  * scope set to an EMPTY list -> NOTHING visible. "Deselected everything" means no data,
                                 NOT "fall back to all" (that was the leak).

Thread-local because team runs drive several agents on threads; each run sets its own
scope. `scoped(...)` is a context manager the orchestrator wraps a run in.
"""
import threading
from contextlib import contextmanager

_local = threading.local()


def set_scope(names):
    """Set the active scope for THIS thread. `names` is a list (possibly empty) of
    allowed source/table/document names, or None to clear (everything visible)."""
    _local.scope = None if names is None else set(names)


def clear_scope():
    _local.scope = None


def _active():
    return getattr(_local, "scope", None)


def is_active():
    """True if a scope is currently set (even an empty one). When False, everything
    is visible and callers can skip scope checks entirely."""
    return _active() is not None


@contextmanager
def scoped(names):
    """Run a block with the given scope, restoring the prior scope afterwards."""
    prev = _active()
    set_scope(names)
    try:
        yield
    finally:
        _local.scope = prev


def allows(*candidates):
    """True if ANY of the given names is in scope (or scope is unset). Used to decide
    whether a source/table/document is visible. With an empty scope, nothing is allowed."""
    sc = _active()
    if sc is None:
        return True
    return any(c in sc for c in candidates if c is not None)


def filter_names(names):
    """Filter an iterable of names to those in scope (all of them if scope is unset)."""
    sc = _active()
    if sc is None:
        return list(names)
    return [n for n in names if n in sc]
