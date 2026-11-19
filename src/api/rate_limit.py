"""
Shared slowapi Limiter instance, imported by both main.py (to attach it to
the app) and any route module that wants to decorate a specific endpoint
with a tighter limit (e.g. login, to slow down brute-force attempts).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
