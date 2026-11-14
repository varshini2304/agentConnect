"""Deterministic response adapter for tests and local workflow demonstrations."""
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any


class FakeResponseAdapter:
    provider_name = "fake"

    def __init__(self, responses: Sequence[Any] | Mapping[int, Any] = ()):
        self._responses = deque(responses) if not isinstance(responses, Mapping) else None
        self._by_agent = dict(responses) if isinstance(responses, Mapping) else None
        self.calls: list[dict[str, Any]] = []

    def generate(self, system_instruction: str, prompt: str, agent_id: int | None = None) -> Any:
        self.calls.append({
            "system_instruction": system_instruction,
            "prompt": prompt,
            "agent_id": agent_id,
        })
        if self._by_agent is not None:
            if agent_id not in self._by_agent:
                raise RuntimeError("fake response not configured")
            result = self._by_agent[agent_id]
        elif self._responses:
            result = self._responses.popleft()
        else:
            raise RuntimeError("fake response queue is empty")
        if isinstance(result, BaseException):
            raise result
        return result
