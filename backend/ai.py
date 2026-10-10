"""Claude API integration — replaces the manual copy-paste-to-a-chat-AI
workflow with a direct call, using AI_EDITING_INSTRUCTIONS.md verbatim as
the system prompt.
"""

from __future__ import annotations

import os
from pathlib import Path

from anthropic import Anthropic

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000  # ceiling only — you're billed for tokens actually generated, not this cap

INSTRUCTIONS_PATH = Path(__file__).resolve().parent.parent / "AI_EDITING_INSTRUCTIONS.md"
PROMPT_MARKER = "## COPY EVERYTHING BELOW THIS LINE INTO THE AI CHAT"


class ClaudeNotConfiguredError(RuntimeError):
    pass


def _load_system_prompt() -> str:
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    if PROMPT_MARKER in text:
        text = text.split(PROMPT_MARKER, 1)[1]
    return text.strip()


SYSTEM_PROMPT = _load_system_prompt()

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ClaudeNotConfiguredError(
                "ANTHROPIC_API_KEY is not set. Export it before starting the server."
            )
        _client = Anthropic(api_key=api_key)
    return _client


def generate_edit(
    messages: list[dict],
    instruction: str,
    vtt_text: str | None,
) -> tuple[str, list[dict]]:
    """Append the new instruction turn, call Claude, return (reply_text, updated_messages).

    On the first call for a project, the user turn includes the full
    TRANSCRIPT. On follow-up calls, Claude already has the whole
    conversation (including its own prior replies) in `messages`, so only
    the new instruction needs to be sent.
    """

    if not messages:
        if not vtt_text:
            raise ValueError("No transcript available for this project yet.")
        user_content = f"INSTRUCTION:\n{instruction}\n\nTRANSCRIPT:\n{vtt_text}"
    else:
        user_content = f"INSTRUCTION:\n{instruction}"

    new_messages = messages + [{"role": "user", "content": user_content}]

    extra_headers = {}
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        extra_headers["anthropic-workspace-id"] = workspace_id

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=new_messages,
        # Caches the system prompt + growing conversation history (transcript,
        # prior REMOVED lists) so each follow-up round only pays full price
        # for the new instruction, not the whole resent history.
        cache_control={"type": "ephemeral"},
        extra_headers=extra_headers,
    )

    # A refusal or a truncated reply would otherwise parse as a short, valid-looking edit list.
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise RuntimeError(f"Claude declined this request (category: {category or 'unspecified'}).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Claude's reply was cut off at the token limit; the edit list is incomplete.")

    reply_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    new_messages = new_messages + [{"role": "assistant", "content": reply_text}]

    return reply_text, new_messages
