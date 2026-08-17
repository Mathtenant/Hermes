"""Edge-case simulation suite (S1-S10).

Fault injection + snapshot/invariant helpers live in ``faults.py`` and
``snapshots.py``; the simulations themselves are split across
``test_sim_p0.py`` (P0 correctness gaps), ``test_sim_faults.py`` (P1
corruption/failure/idempotency), and ``test_sim_load.py`` (P2 resource &
long-running soak proxies, marked ``slow``).

No test in this package touches a live Ollama service or ``data/risks.db``:
every store is opened against ``tmp_path``, and every LLM call is
monkeypatched at the transport layer (``requests.post``) or duck-typed away
with a fake client.
"""
