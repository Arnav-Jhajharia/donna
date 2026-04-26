"""Proactive search subsystem.

Reads the user's current state (Living Profile + Situation Brief + recent
thread) and decides what — if anything — to look up unprompted. The brain
sits in ``query_creation``; ``executor`` dispatches the resulting moves
across Exa's surface (search, find_similar, research, websets, monitors).

This is intent-based search, not search-engine search. Donna doesn't take
the user's query and run it. She *invents* the query the user would
benefit from, before they ask, and only speaks when the answer earns it.
"""
