"""Document deep-ingest pipeline (Donna v2 Phase 2).

Public entry: ``ingest_attachment(user_id, payload, *, source="whatsapp")``
in ``documents``. Adapters in ``ingress/`` call it after the brain turn so
attachment processing never blocks user-perceived latency.
"""
