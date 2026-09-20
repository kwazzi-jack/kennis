"""The terminal front end: one of several, and not a privileged one.

Everything here is presentation. It calls the engine, subscribes to the events
the engine emits, and renders them; it holds no behaviour another front end
could not reach.
"""

from __future__ import annotations
