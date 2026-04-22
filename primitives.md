### tool_name

**Category:** retrieval | action | dashboard | conversation | meta
**Render target:** WhatsApp | dashboard section X | internal state | none

**Description (written as the model will read it):**
What this tool does. When to use it. When NOT to use it. What it returns.

**Input schema:**
- param_name (type): description
- param_name (type): description

**Example trigger:**
"User asks X" → model calls this tool with inputs {...}



### supermemory_targeted_search

**Category:** retrieval
**Render target:** WhatsApp

**Description (written as the model will read it):**
This tool finds targeted items to search for in supermemory about the user, to get further context for better action

**Input schema:**
- param_name (str[]): queries to supermemory to fetch relevant things

**Example trigger:**
"user says something, and the model understands that there is more info that might be useful given the living profile (note, the user may or may not ask for it)" → model calls this tool with inputs queries


**Actual Example**

"What to have for lunch today?" -> "Donna knows the person has diarrhea through existing memory" -> "So she digs deep"


### suggest_tracker

**Category:** action
**Render target:** WhatsApp | dashboard section X | internal state | none

**Description (written as the model will read it):**
What this tool does. When to use it. When NOT to use it. What it returns.

**Input schema:**
- param_name (type): description
- param_name (type): description

**Example trigger:**
"User asks X" → model calls this tool with inputs {...}"


### suggest_tracker

**Category:** action
**Render target:** WhatsApp | dashboard section X | internal state | none

**Description (written as the model will read it):**
What this tool does. When to use it. When NOT to use it. What it returns.

**Input schema:**
- param_name (type): description
- param_name (type): description

**Example trigger:**
"User asks X" → model calls this tool with inputs {...}"