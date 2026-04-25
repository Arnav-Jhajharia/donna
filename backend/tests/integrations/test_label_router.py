from __future__ import annotations

import pytest

from backend.integrations.label_router import classify_depth


@pytest.mark.parametrize(
    "labels,starred,important,sent,expected",
    [
        (["SPAM"], False, False, False, "ignore"),
        (["TRASH"], False, False, False, "ignore"),
        (["DRAFT"], False, False, False, "ignore"),
        (["INBOX", "PRIMARY"], False, False, False, "full"),
        (["INBOX"], False, False, False, "full"),
        (["INBOX", "UPDATES"], False, False, False, "metadata"),
        (["INBOX", "FORUMS"], False, False, False, "metadata"),
        (["INBOX", "SOCIAL"], False, False, False, "metadata"),
        (["INBOX", "PROMOTIONS"], False, False, False, "aggregate"),
        (["INBOX", "PROMOTIONS"], True, False, False, "full"),
        (["INBOX", "UPDATES"], False, True, False, "full"),
        (["SENT"], False, False, True, "full"),
        (["INBOX", "Label_42"], False, False, False, "metadata"),
    ],
)
def test_classify_depth(labels, starred, important, sent, expected) -> None:
    assert (
        classify_depth(
            labels=labels,
            is_starred=starred,
            is_important=important,
            is_sent=sent,
        )
        == expected
    )
