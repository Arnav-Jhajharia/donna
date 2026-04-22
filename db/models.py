import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    phone: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    profession: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Singapore")
    wake_time: Mapped[str | None] = mapped_column(String, nullable=True)
    sleep_time: Mapped[str | None] = mapped_column(String, nullable=True)
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_goals: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {"tz_done": False, "watch_done": False},
    )
    onboarding_node: Mapped[str | None] = mapped_column(String, nullable=True)  # current playbook node_id
    facts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    voice_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_model_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    has_google: Mapped[bool] = mapped_column(Boolean, default=False)
    has_github: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    wa_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_proactive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProceduralRule(Base):
    __tablename__ = "procedural_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Observation(Base):
    """Single tracking table for all countable/measurable user events.

    event_time = when it happened (may differ from created_at)
    tags       = indexed metadata {meal_type: lunch, source: whatsapp}
    fields     = measured values {item: mee pok, calories: 520}
    enriched   = async-populated {protein_g: 18, nutrition_source: usda}
    lineage    = ["whatsapp_capture", "nlp_extraction", "nutrition_api"]

    Types: meal | expense | mood | habit | weight | sleep | exercise | academic | task | custom
    """
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    instance_id: Mapped[str] = mapped_column(String, ForeignKey("donna_instances.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String, default="whatsapp")
    lineage: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_obs_user_type_time", "user_id", "type", "event_time"),
        Index("idx_obs_user_time", "user_id", "event_time"),
        Index("idx_obs_user_instance", "user_id", "instance_id"),
    )


class SchemaRegistry(Base):
    """Census of what observation types exist per user. Perceive reads this as structured_state."""
    __tablename__ = "schema_registry"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OpenLoop(Base):
    """Unresolved threads from past conversations."""
    __tablename__ = "open_loops"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String, default="active")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CalendarEntry(Base):
    """Synced calendar events from Google Calendar (via Composio)."""
    __tablename__ = "calendar_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    google_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_cal_user_start", "user_id", "start_time"),
    )


class Document(Base):
    """Tracks documents uploaded via WhatsApp. Extracted text is stored in extracted_text;
    a short summary episode is ingested into Graphiti for proactive recall."""
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    supermemory_doc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String, default="whatsapp")
    processing_status: Mapped[str] = mapped_column(String, default="processing")  # processing | ready | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_docs_user_created", "user_id", "created_at"),
        Index("idx_docs_user_status", "user_id", "processing_status"),
    )


class DonnaSchedule(Base):
    """Scheduled message to fire at a specific time.

    origin: "user" = user explicitly asked ("remind me at 5pm")
            "donna" = Donna proactively scheduled (good luck before interview, etc.)

    If origin=user and the schedule fires late (server was down), the compose
    directive should include an apology. If origin=donna, just skip silently.
    """
    __tablename__ = "donna_schedule"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    fire_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False, default="donna")  # "user" | "donna"
    recurrence: Mapped[str | None] = mapped_column(String, nullable=True)  # None=one-shot, "daily", "weekdays", "weekly"
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)  # pending | running | done | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_schedule_fire", "fire_at", "fired"),
        Index("idx_schedule_status_fire", "status", "fire_at"),
    )


class DonnaInstance(Base):
    """A real feature Donna is running for a specific user.

    Combines a primitive (verb) + connector (sense) + user-specific config
    into a living feature with its own lifecycle.

    Examples:
        Track(meals) via whatsapp_manual — config: {type: "meal"}
        Watch(aura PRs) via github — config: {repo: "anthropics/aura"}
        Schedule(vitamins) via whatsapp_manual — config: {recurrence: "daily"}
    """
    __tablename__ = "donna_instances"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    primitive: Mapped[str] = mapped_column(String, nullable=False)      # track, schedule, watch, remember, compose
    connector: Mapped[str] = mapped_column(String, nullable=False)      # whatsapp_manual, google_calendar, github, weather
    label: Mapped[str] = mapped_column(String, nullable=False)          # user-facing: "meals", "morning briefing", "coffees"
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # primitive-specific (legacy)
    spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)      # full InstanceSpec JSON (new shape; dispatcher uses this)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active, paused, offered, declined
    offered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_last_fire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_inst_user_status", "user_id", "status"),
        Index("idx_inst_user_primitive", "user_id", "primitive"),
        Index("idx_inst_status_trigger_lock", "status", "trigger_locked_at"),
    )


class RunTrace(Base):
    """Persistent record of a perceive/act turn or a spec fire.

    kind='turn'      → perceive + triage + act for one inbound message
    kind='spec_fire' → a single Runner.fire invocation

    payload shape is defined in the plan (Phase 1.3 / 1.4).
    """
    __tablename__ = "run_traces"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)               # 'turn' | 'spec_fire'
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)  # turn_id or instance_id
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    # 'running' | 'ok' | 'error' | 'skipped' | 'orphaned'
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)       # one-liner for list view
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_traces_user_started", "user_id", "started_at"),
        Index("idx_traces_user_kind_started", "user_id", "kind", "started_at"),
    )


class OAuthToken(Base):
    """Stores OAuth tokens for third-party integrations (Google, etc.)."""
    __tablename__ = "oauth_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)   # "google", "microsoft", etc.
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_oauth_user_provider", "user_id", "provider", unique=True),
    )
