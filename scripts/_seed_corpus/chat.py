"""Chat message generator.

30 days of WhatsApp-like turns. ~50% substantive (named people, topics,
commitments that become open loops) and ~50% chatter. Donna's proactive
messages are marked via ``is_proactive=True``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ChatRow:
    user_id: str
    role: str  # user | assistant
    content: str
    created_at: datetime  # naive UTC
    is_proactive: bool = False


_SUBSTANTIVE: list[tuple[int, int, str, str, bool]] = [
    # (day_offset, local_hour, role, content, is_proactive)
    (-30, 9, "user", "moving the team sync to wednesdays. ravi said he's fine with it.", False),
    (-30, 9, "assistant", "noted. shifting the recurring. anything for maya on that?", False),
    (-29, 11, "user", "maya's prepping the product doc for saurabh. she's stressed.", False),
    (-29, 11, "assistant", "want me watching her commit cadence this week? if it slips below 3/day i flag.", False),
    (-28, 20, "user", "dinner with jess next thursday at the hawker centre. confirm with her.", False),
    (-28, 20, "assistant", "loop open: confirm dinner with jess thursday.", False),
    (-27, 8, "user", "saurabh sent the term sheet. 10m pre, clean terms.", False),
    (-27, 8, "assistant", "holding that thread. want a prep doc before your call with him?", False),
    (-26, 14, "user", "yeah do the prep doc. focus on dilution and the liquidation stack.", False),
    (-25, 21, "user", "toronto feels far. talked to mom, she's doing fine.", False),
    (-24, 10, "user", "stripe is hiring hard in sg. maya saw three of her old colleagues posting.", False),
    (-23, 16, "user", "need to respond to saurabh's term sheet by end of next week.", False),
    (-22, 9, "user", "priya emailed asking about revenue multiples. she's considering an angel ticket.", False),
    (-22, 9, "assistant", "loop: respond to priya on revenue multiples.", False),
    (-21, 19, "user", "ravi pushed back on the burn rate plan. we argued. not productive.", False),
    (-20, 7, "assistant", "morning. you said you'd get the cap table cleaned before saurabh's call. still on?", True),
    (-20, 7, "user", "yeah. today.", False),
    (-19, 12, "user", "maya wants to hire a third eng. disagree but haven't said so.", False),
    (-18, 9, "user", "flying to ny tonight. investor meetings thursday and friday.", False),
    (-18, 9, "assistant", "got it. i'll stop asking about sg timezone things until you're back.", False),
    (-17, 11, "user", "in ny. jetlagged. coffee at la colombe was 6 bucks.", False),
    (-16, 15, "user", "met anthropic folks at a dinner. interesting context on model access pricing.", False),
    (-15, 10, "user", "saurabh agreed to co-invest with priya. 12m pre now, still clean.", False),
    (-15, 10, "assistant", "good. that changes the dilution math. want the prep doc updated?", False),
    (-14, 18, "user", "back in sg. tired.", False),
    (-13, 9, "user", "maya mentioned she wants to revisit the hiring plan. we should talk.", False),
    (-12, 14, "user", "ravi apologized for the burn rate fight. we're good.", False),
    (-11, 20, "user", "tom called from toronto. his startup raised a seed. good for him.", False),
    (-10, 9, "assistant", "you haven't answered priya in 8 days. still planning to?", True),
    (-10, 9, "user", "shit. today.", False),
    (-9, 11, "user", "priya says she'll wire 500k next week. clean.", False),
    (-8, 16, "user", "maya closed the infra migration. 2 days ahead of schedule.", False),
    (-7, 8, "user", "dinner with maya tomorrow night. confirm the place. the japanese spot on amoy st.", False),
    (-7, 8, "assistant", "loop: confirm dinner place with maya for tomorrow.", False),
    (-6, 19, "user", "dinner was good. maya is solid. we're going to win this.", False),
    (-5, 10, "user", "board sync got pushed to next week. jess also wants to catch up.", False),
    (-4, 13, "user", "ravi flagged a churn spike on two enterprise accounts. investigating.", False),
    (-3, 11, "user", "saurabh wants a weekly update. set that up.", False),
    (-3, 11, "assistant", "loop: set up weekly update cadence with saurabh.", False),
    (-2, 20, "user", "anxious about the board sync friday. need to prep.", False),
    (-1, 7, "assistant", "morning. board sync is tomorrow 3pm. the prep doc is half done — finish today?", True),
    (-1, 7, "user", "yeah.", False),
    (0, 9, "user", "good morning.", False),
    (0, 9, "assistant", "board sync in six hours. you're ready.", False),
]


_CHATTER_POOL_USER = [
    "ok",
    "yeah",
    "lol",
    "noted",
    "thanks",
    "sure",
    "tomorrow then",
    "not today",
    "got it",
    "maybe",
    "later",
    "tired",
    "busy",
    "ping me",
    "done",
    "hm",
    "cool",
    "fine",
    "yep",
    "idk",
]

_CHATTER_POOL_ASSISTANT = [
    "noted.",
    "got it.",
    "holding.",
    "later then.",
    "okay.",
    "done.",
    "on it.",
    "tracking.",
    "silent window respected.",
    "here when you need.",
]


def build_chat_rows(
    user_id: str,
    anchor: datetime,
    rng: random.Random,
    *,
    total: int = 200,
) -> list[ChatRow]:
    """Build ~``total`` chat rows ending at ``anchor``. Order: ascending time.

    Substantive anchors are pinned; chatter fills the remaining budget.
    """
    rows: list[ChatRow] = []
    for offset_days, local_hour, role, content, proactive in _SUBSTANTIVE:
        rows.append(
            ChatRow(
                user_id=user_id,
                role=role,
                content=content,
                created_at=anchor + timedelta(days=offset_days, hours=local_hour - 8),
                is_proactive=proactive,
            )
        )

    chatter_budget = max(0, total - len(rows))
    for _ in range(chatter_budget):
        offset_days = rng.randint(-30, 0)
        local_hour = rng.choice([8, 10, 11, 13, 15, 17, 20, 22])
        jitter_minutes = rng.randint(0, 59)
        role = rng.choices(["user", "assistant"], weights=[3, 1])[0]
        content = rng.choice(
            _CHATTER_POOL_USER if role == "user" else _CHATTER_POOL_ASSISTANT
        )
        rows.append(
            ChatRow(
                user_id=user_id,
                role=role,
                content=content,
                created_at=anchor
                + timedelta(days=offset_days, hours=local_hour - 8, minutes=jitter_minutes),
                is_proactive=False,
            )
        )

    rows.sort(key=lambda r: r.created_at)
    # Trim to target if we overshot.
    return [replace(r) for r in rows[:total]]
