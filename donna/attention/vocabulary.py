"""Closed vocabulary for the Attention primitive (v2).

All enums here are the only values the LLM author may pick from. Per-source
Pydantic params models validate the `params` field of each Source at spec-
authoring time.

Guiding principle: every SourceType produces AMBIENT SIGNAL or captures
user-originated observation. No user-organized workspace tools (Notion,
Linear, Airtable, Trello, Asana, ClickUp).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# -- Core enums --------------------------------------------------------------


class SourceType(str, Enum):
    # Communication & conversation (6)
    CALENDAR_EVENTS = "calendar_events"
    GMAIL_INBOX = "gmail_inbox"
    GMAIL_THREAD = "gmail_thread"
    WHATSAPP_CHAT = "whatsapp_chat"
    WHATSAPP_MENTIONS_ENTITY = "whatsapp_mentions_entity"
    SMS_INBOX = "sms_inbox"

    # User memory & state (5) — internal observations + elicitation added
    ENTITY_MEMORY = "entity_memory"
    INTERNAL_EPISODES = "internal_episodes"
    INTERNAL_ATTENTION = "internal_attention"
    INTERNAL_OBSERVATIONS = "internal_observations"
    USER_ELICITATION = "user_elicitation"

    # Web - general & search (3)
    WEB_EXA = "web_exa"
    WEB_GOOGLE_NEWS = "web_google_news"
    WEB_SEARCH_GOOGLE = "web_search_google"

    # Web - community & social (4)
    WEB_HN = "web_hn"
    WEB_REDDIT = "web_reddit"
    WEB_PRODUCTHUNT = "web_producthunt"
    WEB_X_TWITTER = "web_x_twitter"

    # Web - content platforms (4)
    WEB_YOUTUBE = "web_youtube"
    WEB_SUBSTACK = "web_substack"
    WEB_PODCAST_TRANSCRIPT = "web_podcast_transcript"
    WEB_RSS = "web_rss"

    # Web - technical (3)
    WEB_GITHUB_TRENDING = "web_github_trending"
    WEB_GITHUB_REPO = "web_github_repo"
    WEB_ARXIV = "web_arxiv"

    # Web - catch-all (1)
    WEB_DOMAIN = "web_domain"

    # Logistics & commerce APIs (4)
    API_17TRACK = "api_17track"
    API_FLIGHTAWARE = "api_flightaware"
    API_GOOGLE_MAPS = "api_google_maps"
    API_OPENWEATHER = "api_openweather"


class CardType(str, Enum):
    """The six shapes of update an Attention can produce."""

    EVENT_STREAM = "event_stream"
    TALLY = "tally"
    BRIEF = "brief"
    PREP_DOC = "prep_doc"
    OPEN_LOOP = "open_loop"
    PING = "ping"


class SubjectType(str, Enum):
    ENTITY = "entity"
    DOMAIN = "domain"
    EVENT = "event"
    THREAD = "thread"
    SELF = "self"


class CadenceType(str, Enum):
    ON_EVENT = "on_event"
    SCHEDULED = "scheduled"
    ON_RELEVANCE = "on_relevance"
    ONE_SHOT = "one_shot"
    ON_DEMAND = "on_demand"


class SurfaceLevel(str, Enum):
    SILENT = "silent"
    DIGEST = "digest"
    NOTIFY = "notify"
    URGENT = "urgent"


class DomainTag(str, Enum):
    WORK = "work"
    FUNDRAISING = "fundraising"
    SOCIAL = "social"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    LEARNING = "learning"
    HEALTH = "health"
    TRAVEL = "travel"
    COMPETITIVE_INTEL = "competitive_intel"
    MEETING = "meeting"
    RESEARCH = "research"
    SUBSCRIPTION = "subscription"
    SHIPMENT = "shipment"
    FLIGHT = "flight"
    OPENLOOP = "openloop"
    REMINDER = "reminder"
    HABIT = "habit"


# -- Per-source params models ------------------------------------------------


class _ParamsBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CalendarEventsParams(_ParamsBase):
    calendar_id: str = "primary"
    lookahead_days: int = Field(default=7, ge=0, le=365)
    attendee_filter: str | None = None
    title_pattern: str | None = None


class GmailInboxParams(_ParamsBase):
    sender_filter: str | None = None
    subject_pattern: str | None = None
    label: str | None = None
    has_attachment: bool | None = None


class GmailThreadParams(_ParamsBase):
    thread_id: str | None = None
    subject_seed: str | None = None


class WhatsappChatParams(_ParamsBase):
    chat_jid: str | None = None
    sender_filter: str | None = None


class WhatsappMentionsEntityParams(_ParamsBase):
    entity_name: str


class SmsInboxParams(_ParamsBase):
    sender_filter: str | None = None
    keyword: str | None = None


class EntityMemoryParams(_ParamsBase):
    entity_name: str
    relation_filter: str | None = None


class InternalEpisodesParams(_ParamsBase):
    query: str
    lookback_days: int = Field(default=30, ge=1, le=3650)


class InternalAttentionParams(_ParamsBase):
    attention_id: str | None = None
    domain: DomainTag | None = None


class InternalObservationsParams(_ParamsBase):
    """User-logged observations (habits, mood, expenses entered directly)."""

    tag: str
    schema_hint: str | None = None


class UserElicitationParams(_ParamsBase):
    """Donna asks the user for input via WhatsApp (ping / mood / expense log)."""

    question: str = Field(min_length=1, max_length=400)
    expected_shape: Literal["text", "number", "choice", "confirmation"] = "text"
    choices: list[str] | None = None


class WebExaParams(_ParamsBase):
    query: str
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    type: Literal["neural", "keyword", "auto"] = "auto"
    num_results: int = Field(default=10, ge=1, le=50)


class WebGoogleNewsParams(_ParamsBase):
    query: str
    language: str = "en"
    country: str = "US"


class WebSearchGoogleParams(_ParamsBase):
    query: str
    site: str | None = None
    freshness_days: int | None = Field(default=None, ge=1, le=365)


class WebHnParams(_ParamsBase):
    query: str | None = None
    min_points: int = Field(default=0, ge=0)
    tags: list[str] | None = None


class WebRedditParams(_ParamsBase):
    subreddit: str | None = None
    query: str | None = None
    min_upvotes: int = Field(default=0, ge=0)


class WebProducthuntParams(_ParamsBase):
    query: str | None = None
    topic: str | None = None


class WebXTwitterParams(_ParamsBase):
    handles: list[str] | None = None
    query: str | None = None
    min_likes: int = Field(default=0, ge=0)


class WebYoutubeParams(_ParamsBase):
    channel_id: str | None = None
    query: str | None = None


class WebSubstackParams(_ParamsBase):
    publication_url: str | None = None
    author: str | None = None


class WebPodcastTranscriptParams(_ParamsBase):
    podcast_name: str | None = None
    feed_url: str | None = None
    query: str | None = None


class WebRssParams(_ParamsBase):
    feed_url: str


class WebGithubTrendingParams(_ParamsBase):
    language: str | None = None
    since: Literal["daily", "weekly", "monthly"] = "daily"


class WebGithubRepoParams(_ParamsBase):
    repo: str
    watch: Literal["releases", "issues", "prs", "commits", "stars"] = "releases"


class WebArxivParams(_ParamsBase):
    query: str
    categories: list[str] | None = None


class WebDomainParams(_ParamsBase):
    url: str
    selector: str | None = None


class Api17trackParams(_ParamsBase):
    tracking_number: str
    carrier: str | None = None


class ApiFlightawareParams(_ParamsBase):
    flight_number: str | None = None
    ident: str | None = None


class ApiGoogleMapsParams(_ParamsBase):
    origin: str
    destination: str
    mode: Literal["driving", "transit", "walking", "cycling"] = "driving"


class ApiOpenweatherParams(_ParamsBase):
    location: str
    units: Literal["metric", "imperial"] = "metric"


SOURCE_PARAMS_MODELS: dict[SourceType, type[_ParamsBase]] = {
    SourceType.CALENDAR_EVENTS: CalendarEventsParams,
    SourceType.GMAIL_INBOX: GmailInboxParams,
    SourceType.GMAIL_THREAD: GmailThreadParams,
    SourceType.WHATSAPP_CHAT: WhatsappChatParams,
    SourceType.WHATSAPP_MENTIONS_ENTITY: WhatsappMentionsEntityParams,
    SourceType.SMS_INBOX: SmsInboxParams,
    SourceType.ENTITY_MEMORY: EntityMemoryParams,
    SourceType.INTERNAL_EPISODES: InternalEpisodesParams,
    SourceType.INTERNAL_ATTENTION: InternalAttentionParams,
    SourceType.INTERNAL_OBSERVATIONS: InternalObservationsParams,
    SourceType.USER_ELICITATION: UserElicitationParams,
    SourceType.WEB_EXA: WebExaParams,
    SourceType.WEB_GOOGLE_NEWS: WebGoogleNewsParams,
    SourceType.WEB_SEARCH_GOOGLE: WebSearchGoogleParams,
    SourceType.WEB_HN: WebHnParams,
    SourceType.WEB_REDDIT: WebRedditParams,
    SourceType.WEB_PRODUCTHUNT: WebProducthuntParams,
    SourceType.WEB_X_TWITTER: WebXTwitterParams,
    SourceType.WEB_YOUTUBE: WebYoutubeParams,
    SourceType.WEB_SUBSTACK: WebSubstackParams,
    SourceType.WEB_PODCAST_TRANSCRIPT: WebPodcastTranscriptParams,
    SourceType.WEB_RSS: WebRssParams,
    SourceType.WEB_GITHUB_TRENDING: WebGithubTrendingParams,
    SourceType.WEB_GITHUB_REPO: WebGithubRepoParams,
    SourceType.WEB_ARXIV: WebArxivParams,
    SourceType.WEB_DOMAIN: WebDomainParams,
    SourceType.API_17TRACK: Api17trackParams,
    SourceType.API_FLIGHTAWARE: ApiFlightawareParams,
    SourceType.API_GOOGLE_MAPS: ApiGoogleMapsParams,
    SourceType.API_OPENWEATHER: ApiOpenweatherParams,
}


# -- Card → default output schema hints -------------------------------------
# The LLM doesn't author output_schema; it's derived from the card choice.

_CARD_OUTPUT_SCHEMAS: dict[CardType, dict] = {
    CardType.EVENT_STREAM: {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "relevance": {"type": "number"},
                    },
                    "required": ["id", "title"],
                },
            }
        },
        "required": ["events"],
    },
    CardType.TALLY: {
        "type": "object",
        "properties": {
            "count": {"type": "number"},
            "unit": {"type": "string"},
            "window": {"type": "string"},
            "entries": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["count"],
    },
    CardType.BRIEF: {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "bullets"],
    },
    CardType.PREP_DOC: {
        "type": "object",
        "properties": {
            "for_event": {"type": "string"},
            "context": {"type": "string"},
            "talking_points": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["for_event", "talking_points"],
    },
    CardType.OPEN_LOOP: {
        "type": "object",
        "properties": {
            "loop_summary": {"type": "string"},
            "last_activity_at": {"type": "string"},
            "waiting_on": {"type": "string"},
            "is_resolved": {"type": "boolean"},
        },
        "required": ["loop_summary", "is_resolved"],
    },
    CardType.PING: {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "fire_at": {"type": "string"},
        },
        "required": ["message"],
    },
}


def output_schema_for_card(card: CardType) -> dict:
    """Return the JSON schema an Attention of the given card must produce."""
    return _CARD_OUTPUT_SCHEMAS[card]


def vocabulary_summary() -> dict[str, list[str]]:
    """Serializable view of the vocabulary for the authoring prompt."""
    return {
        "source_types": [s.value for s in SourceType],
        "card_types": [c.value for c in CardType],
        "subject_types": [s.value for s in SubjectType],
        "cadence_types": [c.value for c in CadenceType],
        "surface_levels": [s.value for s in SurfaceLevel],
        "domain_tags": [d.value for d in DomainTag],
    }
