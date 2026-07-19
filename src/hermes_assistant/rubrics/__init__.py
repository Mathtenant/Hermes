"""Rubric models & loader — the *program* the critic agent executes.

A rubric decomposes a quality standard into atomic, independently-checkable
criteria plus anti-patterns. The critic (``agents/critic.py``) is the executor:
one ``structured()`` call per criterion (compiler-executor pattern).
"""
