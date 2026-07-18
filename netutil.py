"""
Shared HTTPS helpers, hardened for PyInstaller-frozen builds.

The app's outbound HTTPS (community read, contribution upload) worked instantly
from source but *hung indefinitely* in a packaged --onefile exe on Windows —
verified: the same urllib request that returns in 0.2s from source never
returned in the frozen build. The cause is the default SSL context: on Windows
it loads trusted CA certificates from the OS certificate store, and that load
can stall in a frozen exe (the OS-store plumbing doesn't survive packaging
cleanly). The socket timeout doesn't save us because the stall is in cert
loading, not a socket operation.

The fix is to verify against a CA bundle we ship ourselves — certifi's `.pem` —
so SSL never touches the OS store. certifi is a hard dependency now, and
build_exe.bat collects its data file. From source (certifi absent or present)
this still works; the fallback is the ordinary default context.
"""
from __future__ import annotations

import logging
import ssl

log = logging.getLogger(__name__)

_context: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """A verifying SSL context that doesn't depend on the OS cert store.

    Cached: building it (and importing certifi) once is enough, and it's shared
    safely across threads.
    """
    global _context
    if _context is not None:
        return _context
    try:
        import certifi
        _context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        # No certifi (e.g. a stripped source checkout) — fall back to the
        # default context. Fine when NOT frozen; the frozen build always has
        # certifi via requirements.txt + build_exe.bat.
        log.info("certifi unavailable — using the default SSL context", exc_info=True)
        _context = ssl.create_default_context()
    return _context
