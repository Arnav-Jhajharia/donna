import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
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
    living_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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


class Fact(Base):
    """Bi-temporal facts about the user or their entities.

    Two time axes:
      t_valid_*    — when the fact was true in the real world
      t_recorded_* — when we learned / stopped believing the fact

    A "current belief" row has t_valid_to = NULL and t_recorded_to = NULL.
    Superseded rows close out their t_recorded_to and set superseded_by.
    To correct a historical fact, close t_valid_to and insert a new row
    with the corrected t_valid_from.
    """

    __tablename__ = "facts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    predicate: Mapped[str] = mapped_column(String, nullable=False)
    object: Mapped[str] = mapped_column(Text, nullable=False)
    object_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[str] = mapped_column(String, default="chat", nullable=False)
    t_valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    t_valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_recorded_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    t_recorded_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("facts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_facts_user_subj_pred", "user_id", "subject", "predicate"),
        Index("idx_facts_user_valid_from", "user_id", "t_valid_from"),
        Index("idx_facts_user_recorded_from", "user_id", "t_recorded_from"),
    )


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


class InboundMessage(Base):
    """Durable inbox for WhatsApp inbound messages.

    Every parsed inbound message is persisted before dispatch so a crashed
    or redeployed replica can replay unprocessed rows on startup. Status
    transitions: queued → processed (success) | failed (non-cancel exception).
    Cancelled pipelines leave rows as 'queued' so the restart picks them up.

    body stores the minimal WA envelope needed to re-parse on replay:
        {"message": <raw message dict>, "value": <raw value dict>}
    """
    __tablename__ = "inbound_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    phone: Mapped[str] = mapped_column(String, nullable=False, index=True)
    wa_message_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_inbound_status_phone_received", "status", "phone", "received_at"),
    )


class UserSession(Base):
    """Maps Donna user_id → most-recent Claude Agent SDK session_id.

    The SDK carries conversation history on its side keyed by session_id;
    resuming a session reinstates the full transcript so the brain sees prior
    turns without stuffing them into the prompt. This table is the durable,
    cross-replica replacement for the old local JSON file.
    """
    __tablename__ = "user_sessions"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ImageToolEvent(Base):
    """One row per image-tool invocation outcome — drives caps + observability.

    status values: sent | denied_cooldown | denied_cap | failed_provider | failed_safety
    """
    __tablename__ = "image_tool_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_image_events_user_created", "user_id", "created_at"),
    )


class Integration(Base):
    """Per-user, per-product integration state. Source of truth for the
    [INTEGRATIONS] context block; populated by Composio webhook flow."""
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    product: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    composio_connection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_integrations_user_provider_product",
            "user_id", "provider", "product",
            unique=True,
        ),
    )


class EmailMessage(Base):
    """Local mirror of Gmail messages. Body stored only when label-router
    classified the message as 'full'. Bodies for 'metadata' rows are lazy-
    fetched on demand via read_gmail_thread."""
    __tablename__ = "email_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    from_address: Mapped[str] = mapped_column(String, nullable=False)
    from_name: Mapped[str | None] = mapped_column(String, nullable=True)
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingest_depth: Mapped[str] = mapped_column(String, nullable=False)
    internal_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index(
            "uq_email_user_msg",
            "user_id", "gmail_message_id",
            unique=True,
        ),
        Index("idx_emails_user_date", "user_id", "internal_date"),
        Index("idx_emails_user_thread", "user_id", "thread_id"),
        Index(
            "idx_emails_user_important",
            "user_id", "is_important",
            postgresql_where=sa.text("is_important"),
        ),
    )


class ProactivePing(Base):
    """One row per proactive ping fired. Drives rate limiting + cooldowns.

    source values: 'email' | (future) 'open_loop_age' | 'world_delta' | ...
    suppressed_reason is null when actually fired; set when this row recorded
    a suppression decision instead.
    """
    __tablename__ = "proactive_pings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    message_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    suppressed_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_pings_user_fired", "user_id", "fired_at"),
    )
