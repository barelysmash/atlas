"""Whether this host has POSIX ``flock``, for tests of the briefings writer.

The briefings writer takes an exclusive ``fcntl.flock`` on its lock file; on a
host without ``fcntl`` (simulated with ``sys.modules['fcntl'] = None``) it
raises ``PosixHostRequiredError`` instead. Tests that need a real lock carry
``needs_flock`` (on the test, or as the module's ``pytestmark``), so the list
of tests that skip there is explicit, and any other test that came to depend
on the writer fails rather than skips.

A plain module, imported by the tests with ``from _posix import needs_flock``,
so the check runs once per session whatever pytest's import mode.
"""

from __future__ import annotations

import pytest


def _have_flock() -> bool:
    try:
        import fcntl
    except ImportError:
        return False
    return hasattr(fcntl, "flock")


HAVE_FLOCK = _have_flock()

needs_flock = pytest.mark.skipif(not HAVE_FLOCK, reason="needs POSIX fcntl.flock")
