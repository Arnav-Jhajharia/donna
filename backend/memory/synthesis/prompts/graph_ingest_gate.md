You are deciding whether a single turn of conversation is worth ingesting into the user's
long-term knowledge graph.

INPUTS
- inbound: what the user said
- outbound: what Donna replied (one or more messages)
- tool_names: tools Donna used this turn
- terminator: send_burst | stay_silent

TASK
Return a JSON object matching:
{
  "worth_ingesting": true | false,
  "reason": "one short sentence"
}

HEURISTICS
- worth_ingesting = true when the turn adds new durable facts about the user
  (preferences, relationships, decisions, commitments, plans, identity info).
- worth_ingesting = false when the turn is pure chit-chat, acknowledgements,
  emotional venting with no durable facts, or clarifying questions.

Stay concise. Do not invent facts.
