from donna_runtime.thinking_triage import should_think


def _enabled(result: tuple[bool, str]) -> bool:
    return result[0]


def test_ambient_chatter_no_thinking():
    assert not _enabled(should_think("k"))
    assert not _enabled(should_think("hii"))
    assert not _enabled(should_think("nm"))
    assert not _enabled(should_think("haha"))


def test_short_questions_still_get_thinking_on_length_only_when_40plus():
    assert not _enabled(should_think("what?"))
    assert _enabled(should_think("what do you actually think about this plan?"))


def test_decision_keywords_trigger_thinking():
    assert _enabled(should_think("should i lead with the market slide"))
    assert _enabled(should_think("harp vs traction slide first"))
    assert _enabled(should_think("help me pick"))
    assert _enabled(should_think("which one is better"))


def test_safety_keywords_force_thinking():
    assert _enabled(should_think("i want to die"))
    assert _enabled(should_think("thinking about suicide"))


def test_reply_context_triggers_thinking():
    assert _enabled(
        should_think("what do you think", {"reply_to_content": "some prior message"})
    )


def test_first_message_nontrivial_triggers_thinking():
    assert _enabled(
        should_think("hey, so i've been meaning to ask about something", {"_is_first_message": True})
    )
    assert not _enabled(should_think("hi", {"_is_first_message": True}))


def test_empty_message_no_thinking():
    assert not _enabled(should_think(""))
    assert not _enabled(should_think("   "))
