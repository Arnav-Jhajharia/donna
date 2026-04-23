"""Watch donna's raw SDK stream, block by block."""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.options import build_options


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... <+{len(text) - limit} chars>"


def _print_block(block: Any) -> None:
    if isinstance(block, TextBlock):
        print(f"  [text] {_short(block.text, 500)}")
    elif isinstance(block, ToolUseBlock):
        print(f"  [tool_use] {block.name}({_short(block.input)})  id={block.id}")
    elif isinstance(block, ToolResultBlock):
        print(f"  [tool_result] id={block.tool_use_id}  -> {_short(block.content)}")
    else:
        print(f"  [block:{type(block).__name__}] {_short(block)}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="the message to send to donna")
    parser.add_argument("--user-id", default="stream-demo")
    args = parser.parse_args()

    config = DonnaAgentConfig(user_id=args.user_id)
    options = build_options(config)

    print(f">>> sending: {args.message!r}\n")

    async for message in query(prompt=args.message, options=options):
        kind = type(message).__name__
        if isinstance(message, SystemMessage):
            print(f"[{kind}] subtype={message.subtype}")
        elif isinstance(message, AssistantMessage):
            print(f"[{kind}] model={getattr(message, 'model', '?')}  blocks={len(message.content)}")
            for block in message.content:
                _print_block(block)
        elif isinstance(message, UserMessage):
            print(f"[{kind}] (tool results back to model)")
            for block in message.content:
                _print_block(block)
        elif isinstance(message, ResultMessage):
            print(
                f"[{kind}] stop={message.subtype}  turns={message.num_turns}  "
                f"cost=${getattr(message, 'total_cost_usd', 0):.4f}  session={message.session_id}"
            )
        else:
            print(f"[{kind}] {_short(message)}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
