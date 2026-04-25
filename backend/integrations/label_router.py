"""classify_depth — single source of truth for ingest routing.

Used by both bootstrap and live webhook ingest. Pure function.

Output values:
  - "full"      → store body + metadata
  - "metadata"  → store envelope only (lazy fetch body on demand)
  - "aggregate" → count for sender stats only, do not persist row
  - "ignore"    → drop entirely (spam/trash/drafts)
"""
from __future__ import annotations

from typing import Literal, Sequence

Depth = Literal["full", "metadata", "aggregate", "ignore"]

_GMAIL_SYSTEM_LABELS = {
    "INBOX", "SENT", "DRAFT", "STARRED", "IMPORTANT",
    "TRASH", "SPAM", "CHAT", "UNREAD",
    "CATEGORY_PERSONAL", "PRIMARY",
    "CATEGORY_SOCIAL", "SOCIAL",
    "CATEGORY_PROMOTIONS", "PROMOTIONS",
    "CATEGORY_UPDATES", "UPDATES",
    "CATEGORY_FORUMS", "FORUMS",
}

_PROMO_LABELS = {"PROMOTIONS", "CATEGORY_PROMOTIONS"}
_LOW_VALUE_LABELS = {
    "SOCIAL", "CATEGORY_SOCIAL",
    "UPDATES", "CATEGORY_UPDATES",
    "FORUMS", "CATEGORY_FORUMS",
}


def classify_depth(
    *,
    labels: Sequence[str],
    is_starred: bool,
    is_important: bool,
    is_sent: bool,
) -> Depth:
    label_set = set(labels)

    if label_set & {"SPAM", "TRASH", "DRAFT"}:
        return "ignore"

    if is_starred or is_important or is_sent:
        return "full"

    if "PRIMARY" in label_set or "CATEGORY_PERSONAL" in label_set:
        return "full"

    if label_set & _PROMO_LABELS:
        return "aggregate"

    if label_set & _LOW_VALUE_LABELS:
        return "metadata"

    user_labels = label_set - _GMAIL_SYSTEM_LABELS
    if user_labels:
        return "metadata"

    if "INBOX" in label_set:
        return "full"

    return "metadata"
