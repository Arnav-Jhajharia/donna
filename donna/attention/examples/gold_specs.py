"""Gold examples for Attention spec authoring (v2, card catalog).

15 examples spanning the six card types x core domains. Each example:
  - intent_examples: 3+ paraphrases users might say
  - context_signals: hints the authoring prompt should latch onto
  - spec: a concrete, valid AttentionSpec
  - rationale: per-section reasoning (aids few-shot learning)

Every spec uses ambient-signal sources only (including the internal
observations + user_elicitation channels — both originate from the user,
never from user-organized workspaces).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from donna.attention.schema import (
    AttentionSpec,
    Cadence,
    Dedup,
    Extractor,
    NudgePolicy,
    Source,
    Subject,
    SurfaceEscalation,
    SurfacePolicy,
)
from donna.attention.vocabulary import (
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
)


@dataclass(frozen=True)
class GoldExample:
    example_id: str
    intent_examples: tuple[str, ...]
    context_signals: tuple[str, ...]
    spec: AttentionSpec
    rationale: dict[str, str] = field(default_factory=dict)


# -- Spec builders ----------------------------------------------------------


def _poke_watch() -> AttentionSpec:
    return AttentionSpec(
        title="Poke watch",
        description="Ambient monitoring of Poke (competitor) for material updates.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="Poke", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.COMPETITIVE_INTEL, DomainTag.WORK],
        sources=[
            Source(type=SourceType.WEB_EXA, params={"query": "Poke AI startup", "num_results": 10}),
            Source(type=SourceType.WEB_GOOGLE_NEWS, params={"query": "Poke AI"}),
            Source(type=SourceType.WEB_X_TWITTER, params={"query": "Poke AI", "min_likes": 25}),
        ],
        extractor=Extractor(
            prompt="Extract material product, funding, leadership, or positioning events about Poke."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="event_type in ['funding','major_launch','leadership_change']",
        ),
        relevance_threshold=0.6,
    )


def _series_a_watch() -> AttentionSpec:
    return AttentionSpec(
        title="Series A news in our space",
        description="Competitor fundraising news in the ambient agent space.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="ambient agents", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.FUNDRAISING, DomainTag.COMPETITIVE_INTEL],
        sources=[
            Source(type=SourceType.WEB_GOOGLE_NEWS, params={"query": "ambient agent Series A"}),
            Source(type=SourceType.WEB_EXA, params={"query": "ambient agent startup Series A funding"}),
        ],
        extractor=Extractor(prompt="Extract Series A announcements; include company, amount, lead investor."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 10 * * 1-5"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="amount_usd >= 10_000_000",
        ),
        relevance_threshold=0.65,
    )


def _arxiv_rag() -> AttentionSpec:
    return AttentionSpec(
        title="RAG evaluation papers",
        description="New arxiv papers on RAG evaluation methods.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="RAG evaluation", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.LEARNING, DomainTag.RESEARCH],
        sources=[
            Source(
                type=SourceType.WEB_ARXIV,
                params={"query": "retrieval augmented generation evaluation", "categories": ["cs.CL", "cs.IR"]},
            ),
        ],
        extractor=Extractor(prompt="Extract paper title, authors, and one-line contribution."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 8 * * 1"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.DIGEST),
        relevance_threshold=0.55,
    )


def _shipment_track() -> AttentionSpec:
    return AttentionSpec(
        title="Shipment 1Z999",
        description="Track shipment until delivered.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="1Z999", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.SHIPMENT, DomainTag.LOGISTICS],
        sources=[Source(type=SourceType.API_17TRACK, params={"tracking_number": "1Z999"})],
        extractor=Extractor(prompt="Extract status changes with timestamp and location."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"interval_seconds": 3600}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.SILENT,
            urgent_if="status in ['out_for_delivery','delivered','exception']",
            resolve_if="status == 'delivered'",
        ),
        relevance_threshold=0.5,
        dedup=Dedup(key="status", window_size=20),
    )


def _subscriptions_tally() -> AttentionSpec:
    return AttentionSpec(
        title="Subscription spend",
        description="Tally recurring subscription charges from inbox receipts.",
        card=CardType.TALLY,
        subject=Subject(name="subscriptions", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.FINANCE, DomainTag.SUBSCRIPTION],
        sources=[
            Source(
                type=SourceType.GMAIL_INBOX,
                params={"subject_pattern": "receipt|invoice|subscription|renewal"},
            ),
        ],
        extractor=Extractor(prompt="Extract amount, merchant, billing cycle from each receipt."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 1 * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.SILENT,
            urgent_if="month_over_month_change_pct > 15",
        ),
        relevance_threshold=0.7,
    )


def _sleep_tally() -> AttentionSpec:
    return AttentionSpec(
        title="Sleep quality",
        description="Monthly tally of self-reported sleep quality scores.",
        card=CardType.TALLY,
        subject=Subject(name="sleep", type=SubjectType.SELF),
        domain_tags=[DomainTag.HEALTH, DomainTag.HABIT],
        sources=[
            Source(
                type=SourceType.INTERNAL_OBSERVATIONS,
                params={"tag": "sleep_quality", "schema_hint": "score:int 1-10, hours:float"},
            ),
        ],
        extractor=Extractor(prompt="Sum entries, compute average score over the month."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * 0"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            escalations=[
                SurfaceEscalation(condition="avg_score < 5 and trend == 'down'", level=SurfaceLevel.NOTIFY)
            ],
            nudge_policy=NudgePolicy(if_silent_for_seconds=60 * 60 * 36, nudge_text="how did you sleep?"),
        ),
        relevance_threshold=0.5,
    )


def _water_habit() -> AttentionSpec:
    return AttentionSpec(
        title="Water intake",
        description="Daily tally of glasses of water from user check-ins.",
        card=CardType.TALLY,
        subject=Subject(name="water", type=SubjectType.SELF),
        domain_tags=[DomainTag.HABIT, DomainTag.HEALTH],
        sources=[
            Source(
                type=SourceType.INTERNAL_OBSERVATIONS,
                params={"tag": "water_glasses", "schema_hint": "glasses:int"},
            ),
        ],
        extractor=Extractor(prompt="Sum glasses for the current day."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 21 * * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.SILENT,
            escalations=[
                SurfaceEscalation(condition="glasses < 4 and hours_left < 3", level=SurfaceLevel.NOTIFY)
            ],
            nudge_policy=NudgePolicy(if_silent_for_seconds=60 * 60 * 6, nudge_text="how many glasses today?"),
        ),
        relevance_threshold=0.5,
    )


def _weekly_brief() -> AttentionSpec:
    return AttentionSpec(
        title="Weekly work brief",
        description="Friday evening recap of the past week's calendar + email.",
        card=CardType.BRIEF,
        subject=Subject(name="my week", type=SubjectType.SELF),
        domain_tags=[DomainTag.WORK, DomainTag.MEETING],
        sources=[
            Source(type=SourceType.CALENDAR_EVENTS, params={"lookahead_days": 0}),
            Source(type=SourceType.GMAIL_INBOX, params={}),
        ],
        extractor=Extractor(
            prompt="Synthesize: what shipped, who I met, what's unresolved, top three priorities for next week."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 18 * * 5"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.5,
    )


def _podcast_brief() -> AttentionSpec:
    return AttentionSpec(
        title="Podcast digest",
        description="Weekly digest of new Lex Fridman episodes.",
        card=CardType.BRIEF,
        subject=Subject(name="Lex Fridman podcast", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.LEARNING],
        sources=[
            Source(
                type=SourceType.WEB_PODCAST_TRANSCRIPT,
                params={"podcast_name": "Lex Fridman Podcast"},
            ),
        ],
        extractor=Extractor(prompt="For each new episode, headline + 3 key bullet points + one memorable quote."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * 1"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.DIGEST),
        relevance_threshold=0.5,
    )


def _sarah_prep() -> AttentionSpec:
    return AttentionSpec(
        title="Prep for 1:1 with Sarah",
        description="Prep doc ahead of any calendar event titled 1:1 with Sarah.",
        card=CardType.PREP_DOC,
        subject=Subject(name="Sarah", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.MEETING, DomainTag.WORK],
        sources=[
            Source(
                type=SourceType.CALENDAR_EVENTS,
                params={"title_pattern": "1:1 with Sarah", "lookahead_days": 7},
            ),
            Source(type=SourceType.ENTITY_MEMORY, params={"entity_name": "Sarah"}),
            Source(type=SourceType.GMAIL_INBOX, params={"sender_filter": "sarah@"}),
        ],
        extractor=Extractor(
            prompt="For the upcoming 1:1, list context since last sync, open threads, and three talking points."
        ),
        cadence=Cadence(
            type=CadenceType.ON_EVENT, params={"event_source": "calendar_events", "lead_minutes": 60}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.6,
    )


def _flight_prep() -> AttentionSpec:
    return AttentionSpec(
        title="Flight prep",
        description="Prep 2 hours before any flight.",
        card=CardType.PREP_DOC,
        subject=Subject(name="upcoming flight", type=SubjectType.EVENT),
        domain_tags=[DomainTag.FLIGHT, DomainTag.TRAVEL],
        sources=[
            Source(type=SourceType.CALENDAR_EVENTS, params={"title_pattern": "flight|airline|boarding"}),
            Source(type=SourceType.API_FLIGHTAWARE, params={}),
            Source(type=SourceType.API_OPENWEATHER, params={"location": "destination"}),
        ],
        extractor=Extractor(
            prompt="For the next flight, list gate, boarding time, delay status, weather at destination."
        ),
        cadence=Cadence(
            type=CadenceType.ON_EVENT, params={"event_source": "calendar_events", "lead_minutes": 120}
        ),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.NOTIFY,
            urgent_if="delay_minutes >= 30 or gate_changed",
        ),
        relevance_threshold=0.6,
    )


def _investor_loop() -> AttentionSpec:
    return AttentionSpec(
        title="Investor follow-ups",
        description="Open loops with investors awaiting a reply.",
        card=CardType.OPEN_LOOP,
        subject=Subject(name="investor threads", type=SubjectType.THREAD),
        domain_tags=[DomainTag.FUNDRAISING, DomainTag.OPENLOOP],
        sources=[
            Source(
                type=SourceType.GMAIL_INBOX,
                params={"label": "investors"},
            ),
        ],
        extractor=Extractor(
            prompt="For each investor thread, detect if waiting on me or them; flag >7d stale from my side."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 10 * * 1-5"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="waiting_on == 'me' and days_stale >= 7",
            resolve_if="is_resolved == true",
        ),
        relevance_threshold=0.55,
    )


def _texts_loop() -> AttentionSpec:
    return AttentionSpec(
        title="Texts awaiting reply",
        description="WhatsApp chats where a friend is waiting on me.",
        card=CardType.OPEN_LOOP,
        subject=Subject(name="pending replies", type=SubjectType.THREAD),
        domain_tags=[DomainTag.SOCIAL, DomainTag.OPENLOOP],
        sources=[Source(type=SourceType.WHATSAPP_CHAT, params={})],
        extractor=Extractor(
            prompt="Detect chats where the last inbound message is unanswered for >24h and is not a group chat."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 19 * * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="days_stale >= 3",
            resolve_if="is_resolved == true",
        ),
        relevance_threshold=0.5,
    )


def _call_mom_ping() -> AttentionSpec:
    return AttentionSpec(
        title="Call mom",
        description="One-shot reminder to call mom at 6pm.",
        card=CardType.PING,
        subject=Subject(name="call mom", type=SubjectType.EVENT),
        domain_tags=[DomainTag.SOCIAL, DomainTag.REMINDER],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": "call mom?", "expected_shape": "confirmation"},
            ),
        ],
        extractor=Extractor(prompt="Deliver the ping message at the trigger time."),
        cadence=Cadence(
            type=CadenceType.ONE_SHOT, params={"trigger_at": "2026-04-21T18:00:00Z"}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.5,
    )


def _rbi_rate_watch() -> AttentionSpec:
    return AttentionSpec(
        title="RBI rate decision watch",
        description="Ambient monitoring of Reserve Bank of India for monetary policy and repo rate decisions.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="RBI", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.FINANCE, DomainTag.WORK],
        sources=[
            Source(
                type=SourceType.WEB_GOOGLE_NEWS,
                params={"query": "RBI repo rate monetary policy India", "country": "IN"},
            ),
            Source(
                type=SourceType.WEB_RSS,
                params={"feed_url": "https://www.rbi.org.in/Scripts/Rss.aspx"},
            ),
            Source(
                type=SourceType.WEB_EXA,
                params={"query": "Reserve Bank of India repo rate decision MPC", "num_results": 10},
            ),
        ],
        extractor=Extractor(
            prompt="Extract RBI MPC outcomes: rate change direction, basis points, stance, next meeting."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 10 * * 1-5"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="event_type in ['rate_decision','policy_stance_change']",
        ),
        relevance_threshold=0.6,
    )


def _iras_gst_refund_loop() -> AttentionSpec:
    return AttentionSpec(
        title="IRAS GST refund chase",
        description="Open loop tracking the IRAS GST refund until it lands.",
        card=CardType.OPEN_LOOP,
        subject=Subject(name="IRAS GST refund", type=SubjectType.THREAD),
        domain_tags=[DomainTag.FINANCE, DomainTag.OPENLOOP],
        sources=[
            Source(
                type=SourceType.GMAIL_INBOX,
                params={"subject_pattern": "iras|gst|refund|tax"},
            ),
            Source(
                type=SourceType.INTERNAL_OBSERVATIONS,
                params={"tag": "iras_gst_refund", "schema_hint": "status:str, last_update:date"},
            ),
        ],
        extractor=Extractor(
            prompt="Detect IRAS refund status: filed, processing, approved, paid. Flag if stale >10 days."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * 1-5"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="days_stale >= 10",
            resolve_if="status == 'paid'",
        ),
        relevance_threshold=0.55,
    )


def _ica_ep_renewal_watch() -> AttentionSpec:
    return AttentionSpec(
        title="ICA EP renewal policy watch",
        description="Ambient monitoring of ICA for Employment Pass renewal policy changes.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="ICA EP policy", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.WORK, DomainTag.RESEARCH],
        sources=[
            Source(
                type=SourceType.WEB_SEARCH_GOOGLE,
                params={"query": "employment pass renewal rules site:ica.gov.sg", "site": "ica.gov.sg"},
            ),
            Source(
                type=SourceType.WEB_GOOGLE_NEWS,
                params={"query": "Singapore ICA Employment Pass renewal policy", "country": "SG"},
            ),
            Source(
                type=SourceType.WEB_EXA,
                params={"query": "Singapore ICA EP renewal rule change", "num_results": 10},
            ),
        ],
        extractor=Extractor(
            prompt="Extract EP renewal rule changes: eligibility, salary thresholds, processing time, deadlines."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 10 * * 1"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="event_type == 'policy_change'",
        ),
        relevance_threshold=0.6,
    )


def _sgx_nifty_weekly_brief() -> AttentionSpec:
    return AttentionSpec(
        title="SGX and Nifty weekly brief",
        description="Friday evening recap of SGX and Nifty market moves for the week.",
        card=CardType.BRIEF,
        subject=Subject(name="SGX and Nifty", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.FINANCE, DomainTag.WORK],
        sources=[
            Source(
                type=SourceType.WEB_GOOGLE_NEWS,
                params={"query": "Nifty 50 weekly close sensex", "country": "IN"},
            ),
            Source(
                type=SourceType.WEB_GOOGLE_NEWS,
                params={"query": "SGX STI weekly close Singapore", "country": "SG"},
            ),
            Source(
                type=SourceType.WEB_SEARCH_GOOGLE,
                params={"query": "Nifty weekly performance sectors", "freshness_days": 7},
            ),
            Source(
                type=SourceType.WEB_SEARCH_GOOGLE,
                params={"query": "SGX STI weekly movers", "freshness_days": 7},
            ),
        ],
        extractor=Extractor(
            prompt="Summarise week-on-week index moves, top sector winners/losers, notable SG and IN stocks."
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 18 * * 5"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.55,
    )


def _mcst_monthly_ping() -> AttentionSpec:
    return AttentionSpec(
        title="MCST payment reminder",
        description="Monthly ping on the 5th to pay MCST maintenance fees.",
        card=CardType.PING,
        subject=Subject(name="MCST payment", type=SubjectType.EVENT),
        domain_tags=[DomainTag.REMINDER, DomainTag.FINANCE],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": "pay mcst for this month?", "expected_shape": "confirmation"},
            ),
        ],
        extractor=Extractor(prompt="Deliver the MCST payment reminder on the scheduled day."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 5 * *"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.5,
    )


def _dbs_rm_prep() -> AttentionSpec:
    return AttentionSpec(
        title="Prep for DBS RM meeting",
        description="Prep doc ahead of any calendar event with the DBS relationship manager.",
        card=CardType.PREP_DOC,
        subject=Subject(name="DBS RM", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.MEETING, DomainTag.FINANCE],
        sources=[
            Source(
                type=SourceType.CALENDAR_EVENTS,
                params={"title_pattern": "dbs|rm|relationship manager", "lookahead_days": 14},
            ),
            Source(type=SourceType.ENTITY_MEMORY, params={"entity_name": "DBS RM"}),
            Source(type=SourceType.GMAIL_INBOX, params={"sender_filter": "dbs"}),
        ],
        extractor=Extractor(
            prompt="For the DBS RM meeting, list account context, open items, questions to ask, docs to bring."
        ),
        cadence=Cadence(
            type=CadenceType.ON_EVENT, params={"event_source": "calendar_events", "lead_minutes": 60}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.6,
    )


def _hdb_lease_ping() -> AttentionSpec:
    return AttentionSpec(
        title="HDB lease renewal reminder",
        description="One-shot reminder to renew HDB lease in March 2027.",
        card=CardType.PING,
        subject=Subject(name="HDB lease renewal", type=SubjectType.EVENT),
        domain_tags=[DomainTag.REMINDER, DomainTag.WORK],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": "renew hdb lease now?", "expected_shape": "confirmation"},
            ),
        ],
        extractor=Extractor(prompt="Deliver the HDB lease renewal reminder at the trigger time."),
        cadence=Cadence(
            type=CadenceType.ONE_SHOT, params={"trigger_at": "2027-03-01T09:00:00+08:00"}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.5,
    )


def _grab_spend_tally() -> AttentionSpec:
    return AttentionSpec(
        title="Grab spend tally",
        description="Monthly tally of Grab charges from inbox receipts.",
        card=CardType.TALLY,
        subject=Subject(name="grab spend", type=SubjectType.DOMAIN),
        domain_tags=[DomainTag.FINANCE, DomainTag.SUBSCRIPTION],
        sources=[
            Source(
                type=SourceType.GMAIL_INBOX,
                params={"sender_filter": "grab", "subject_pattern": "receipt|charge"},
            ),
        ],
        extractor=Extractor(prompt="Extract amount and ride/food category from each Grab receipt."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 21 * * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.SILENT,
            urgent_if="month_to_date_sgd > 400",
        ),
        relevance_threshold=0.6,
    )


def _mood_ping() -> AttentionSpec:
    return AttentionSpec(
        title="Mood check-in",
        description="Daily mood check-in at 8pm.",
        card=CardType.PING,
        subject=Subject(name="mood", type=SubjectType.SELF),
        domain_tags=[DomainTag.HABIT, DomainTag.HEALTH],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={
                    "question": "how's your mood today? 1-10",
                    "expected_shape": "number",
                },
            ),
        ],
        extractor=Extractor(prompt="Deliver the mood check-in question."),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 20 * * *"}),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        relevance_threshold=0.5,
    )


# -- Gold example assembly -------------------------------------------------


GOLD_EXAMPLES: tuple[GoldExample, ...] = (
    GoldExample(
        example_id="poke_watch",
        intent_examples=(
            "keep an eye on Poke",
            "watch what Poke is doing",
            "let me know if Poke ships anything",
        ),
        context_signals=("competitor name", "ongoing monitoring", "material events only"),
        spec=_poke_watch(),
        rationale={
            "card": "Event stream of discrete updates about one entity.",
            "sources": "Web news + exa + twitter covers PR, product, and positioning.",
            "cadence": "Daily digest — weekly is too sparse for a competitor.",
        },
    ),
    GoldExample(
        example_id="series_a_watch",
        intent_examples=(
            "watch for any Series A news about our competitors",
            "tell me when ambient agent startups raise",
            "news on Series A rounds in our space",
        ),
        context_signals=("domain-level subject", "funding trigger"),
        spec=_series_a_watch(),
        rationale={"card": "Event stream keyed on domain, not entity."},
    ),
    GoldExample(
        example_id="arxiv_rag",
        intent_examples=(
            "follow the latest arxiv papers on RAG evaluation",
            "what's new on arxiv for retrieval eval",
            "notify me about new RAG eval papers",
        ),
        context_signals=("arxiv-specific", "weekly Monday cadence"),
        spec=_arxiv_rag(),
        rationale={"sources": "WEB_ARXIV is purpose-built here; don't use exa."},
    ),
    GoldExample(
        example_id="shipment_1z999",
        intent_examples=(
            "monitor shipment 1Z999",
            "track this package 1Z999",
            "tell me when 1Z999 arrives",
        ),
        context_signals=("tracking number", "auto-resolve on delivery"),
        spec=_shipment_track(),
        rationale={"resolve_if": "Shipment attentions naturally terminate on delivery."},
    ),
    GoldExample(
        example_id="subscriptions_tally",
        intent_examples=(
            "track how much I spend on subscriptions",
            "tally my subscription spend",
            "count my monthly subscription charges",
        ),
        context_signals=("tally by month", "receipt-bearing emails"),
        spec=_subscriptions_tally(),
        rationale={"card": "Tally over receipts; alert on month-over-month jump."},
    ),
    GoldExample(
        example_id="sleep_tally",
        intent_examples=(
            "track my sleep quality over the month",
            "log my sleep scores",
            "how is my sleep trending",
        ),
        context_signals=("user-logged observation", "trend alerting"),
        spec=_sleep_tally(),
        rationale={"source": "INTERNAL_OBSERVATIONS is the right channel for self-logged data."},
    ),
    GoldExample(
        example_id="water_habit",
        intent_examples=(
            "track my water intake",
            "remind me to drink water",
            "keep a count of glasses per day",
        ),
        context_signals=("habit", "nudge policy"),
        spec=_water_habit(),
        rationale={"nudge": "Silent by default; nudge via WhatsApp if data goes stale."},
    ),
    GoldExample(
        example_id="weekly_brief",
        intent_examples=(
            "summarize my week every Friday evening",
            "recap the week each Friday",
            "give me a weekly review",
        ),
        context_signals=("synthesis across sources", "scheduled cron"),
        spec=_weekly_brief(),
        rationale={"card": "Brief synthesizes across sources into one artifact."},
    ),
    GoldExample(
        example_id="podcast_brief",
        intent_examples=(
            "brief me on new Lex Fridman episodes",
            "digest Lex Fridman's new podcast",
            "summarize Lex's latest episodes",
        ),
        context_signals=("podcast entity", "weekly"),
        spec=_podcast_brief(),
        rationale={"sources": "Podcast transcript source; weekly cadence matches release rhythm."},
    ),
    GoldExample(
        example_id="sarah_prep",
        intent_examples=(
            "brief me before my 1:1 with Sarah",
            "prep doc for Sarah 1:1",
            "context for next Sarah sync",
        ),
        context_signals=("calendar-event trigger", "entity memory"),
        spec=_sarah_prep(),
        rationale={"cadence": "ON_EVENT with lead_minutes keyed to the calendar entry."},
    ),
    GoldExample(
        example_id="flight_prep",
        intent_examples=(
            "remind me 2 hours before any flight",
            "prep me before flights",
            "give me flight status 2h ahead",
        ),
        context_signals=("calendar trigger", "multi-source prep"),
        spec=_flight_prep(),
        rationale={"sources": "Flight-specific prep fuses calendar, flight status, and weather."},
    ),
    GoldExample(
        example_id="investor_loop",
        intent_examples=(
            "close the loop on investor follow ups",
            "track pending investor replies",
            "who haven't I gotten back to from investors",
        ),
        context_signals=("open loop", "stale detection"),
        spec=_investor_loop(),
        rationale={"card": "Open loop tracks pending replies; resolve_if closes the card."},
    ),
    GoldExample(
        example_id="texts_loop",
        intent_examples=(
            "which friends am I behind on replying to",
            "texts I haven't replied to",
            "close the loop on pending texts",
        ),
        context_signals=("whatsapp", "waiting-on-me"),
        spec=_texts_loop(),
        rationale={"sources": "WhatsApp chat history, filtered to last-inbound stale > 24h."},
    ),
    GoldExample(
        example_id="call_mom_ping",
        intent_examples=(
            "remind me to call mom at 6pm",
            "ping me at 6 to call mom",
            "don't let me forget to call mom tonight",
        ),
        context_signals=("ping", "one-shot time"),
        spec=_call_mom_ping(),
        rationale={"card": "Bare reminder → card=Ping short-circuit."},
    ),
    GoldExample(
        example_id="rbi_rate_watch",
        intent_examples=(
            "watch rbi for rate decisions",
            "ping me when rbi moves rates",
            "keep an eye on indian monetary policy",
            "let me know when repo rate changes",
        ),
        context_signals=("rbi", "repo rate", "mpc", "india monetary policy", "rate decision"),
        spec=_rbi_rate_watch(),
        rationale={
            "card": "Event stream on an indian regulator entity.",
            "sources": "News + official RSS + exa catches RBI MPC calls and policy stance shifts.",
        },
    ),
    GoldExample(
        example_id="iras_gst_refund_loop",
        intent_examples=(
            "chase the iras gst refund",
            "track my iras gst refund, nudge me if nothing in 10 days",
            "follow up on the singapore gst refund",
            "keep tabs on my iras tax refund",
        ),
        context_signals=("iras", "gst", "refund", "singapore tax", "stale follow up"),
        spec=_iras_gst_refund_loop(),
        rationale={
            "card": "Open loop — the refund is pending and terminates when paid.",
            "sources": "Inbox receipts from iras plus self-logged status observations.",
        },
    ),
    GoldExample(
        example_id="ica_ep_renewal_watch",
        intent_examples=(
            "watch ica for ep renewal policy changes",
            "keep an eye on ica for anything about ep renewal rules",
            "notify me if singapore employment pass rules shift",
            "track ica ep renewal policy",
        ),
        context_signals=("ica", "employment pass", "ep renewal", "singapore immigration", "policy change"),
        spec=_ica_ep_renewal_watch(),
        rationale={
            "card": "Event stream on a regulatory domain with infrequent but material changes.",
            "sources": "Site search of ica.gov.sg plus general news plus exa.",
        },
    ),
    GoldExample(
        example_id="sgx_nifty_weekly_brief",
        intent_examples=(
            "every friday summarise sgx and nifty",
            "give me a weekly sgx and nifty brief",
            "recap how nifty and sgx moved this week",
            "friday evening markets digest for india and singapore",
        ),
        context_signals=("sgx", "nifty", "sti", "weekly brief", "india singapore markets"),
        spec=_sgx_nifty_weekly_brief(),
        rationale={
            "card": "Brief synthesises index moves across two geographies.",
            "cadence": "Friday 6pm cron fits the weekly market close rhythm.",
        },
    ),
    GoldExample(
        example_id="mcst_monthly_ping",
        intent_examples=(
            "remind me to pay mcst on the 5th",
            "ping me every month on the 5th to pay mcst",
            "monthly mcst maintenance reminder",
            "don't let me forget mcst payment each month",
        ),
        context_signals=("mcst", "condo maintenance", "monthly bill", "singapore", "payment reminder"),
        spec=_mcst_monthly_ping(),
        rationale={
            "card": "Bare recurring reminder → ping with a user elicitation source.",
            "cadence": "Scheduled cron on day 5 of each month.",
        },
    ),
    GoldExample(
        example_id="dbs_rm_prep",
        intent_examples=(
            "brief me before my dbs rm meeting",
            "prep doc for the dbs relationship manager sync",
            "context for next meeting with my dbs rm",
            "get me ready for the dbs rm call",
        ),
        context_signals=("dbs", "relationship manager", "private bank", "meeting prep", "singapore"),
        spec=_dbs_rm_prep(),
        rationale={
            "card": "Prep doc triggered by a calendar event with a known entity.",
            "sources": "Calendar title match plus entity memory plus inbox from the bank domain.",
        },
    ),
    GoldExample(
        example_id="hdb_lease_ping",
        intent_examples=(
            "remind me to renew hdb lease in march 2027",
            "one-shot reminder to sort my hdb lease next march",
            "ping me march 2027 for hdb renewal",
        ),
        context_signals=("hdb", "lease renewal", "singapore housing", "one shot", "future reminder"),
        spec=_hdb_lease_ping(),
        rationale={
            "card": "Ping with ONE_SHOT cadence at a specific future date.",
        },
    ),
    GoldExample(
        example_id="grab_spend_tally",
        intent_examples=(
            "track my grab spend monthly",
            "tally my grab charges",
            "how much am i spending on grab",
            "flag if my grab bill crosses 400 sgd",
        ),
        context_signals=("grab", "ride hailing", "food delivery", "monthly spend", "singapore"),
        spec=_grab_spend_tally(),
        rationale={
            "card": "Tally over gmail receipts; threshold alert on month-to-date total.",
        },
    ),
    GoldExample(
        example_id="mood_ping",
        intent_examples=(
            "ask me about my mood every evening",
            "daily mood check-in",
            "ping me at 8pm to log my mood",
        ),
        context_signals=("recurring ping", "user elicitation"),
        spec=_mood_ping(),
        rationale={"card": "Ping for recurring check-ins; pair with a tally to aggregate later."},
    ),
)
