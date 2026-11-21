"""Where ``restaurantos serve`` listens by default.

Kept apart from ``restaurantos.api`` so the CLI can name the defaults in its
help text without importing the server (and with it ``http.server``).
"""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790
