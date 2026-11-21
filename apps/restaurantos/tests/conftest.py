"""Shared test configuration for the restaurantos suite.

Tests that need the briefings writer's POSIX ``flock`` are marked explicitly
with ``needs_flock`` from ``tests/_posix.py``; nothing here turns an error into
a skip.
"""
