"""BaseAgent — shared run-loop plumbing for all six specialized agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..llm.provider import LLMProvider
from ..models import Task, TaskResult
from ..safety.quoting import SAFETY_PREAMBLE, SYSTEM_CITATION_POLICY
from ..storage import Conn
from ..tools.registry import AGENT_TOOLS, ToolRegistry


@dataclass
class AgentDeps:
    """Bundle of resources every agent needs."""

    cfg: Config
    db: Conn
    llm: LLMProvider
    tools: ToolRegistry


class BaseAgent:
    name: str = "base"

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    # Subclasses override
    async def execute(self, task: Task) -> TaskResult:  # pragma: no cover
        raise NotImplementedError

    # ----------------------------- helpers ----------------------------- #

    def _has_web_search(self) -> bool:
        """Whether this agent utilizes web search tools."""
        return "web_search" in AGENT_TOOLS.get(self.name, set())

    def _system_prompt_header(self) -> str:
        """Common safety preamble prepended to every agent's system prompt."""
        header = (
            f"You are the {self.name} agent in a multi-agent scientific research system. "
            f"Operate carefully and cite your sources. {SAFETY_PREAMBLE}"
        )
        if self._has_web_search():
            header = f"{header}\n\n{SYSTEM_CITATION_POLICY}"
        return header

    @staticmethod
    def _final_tool_use(response, tool_name: str) -> dict[str, Any] | None:
        """Find the most recent structured tool record in any provider response.

        API providers expose tool calls as raw blocks. CLI providers capture the same
        calls through MCP and expose them on ``response.capture.records`` instead.
        """
        for block in reversed(response.raw.content or []):
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool_name:
                inp = getattr(block, "input", None)
                return dict(inp) if isinstance(inp, dict) else None
        capture = getattr(response, "capture", None)
        for name, payload in reversed(getattr(capture, "records", ()) or ()):
            if name == tool_name and isinstance(payload, dict):
                return dict(payload)
        return None

    @staticmethod
    def _final_text(response) -> str:
        parts = []
        for block in response.raw.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "\n".join(parts).strip()
