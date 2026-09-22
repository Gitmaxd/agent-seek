"""Discover provider interface (Brave stub reserved)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.models import Candidate


class DiscoverProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, query: str, count: int) -> list[Candidate]:
        raise NotImplementedError


class BraveDiscoverStub(DiscoverProvider):
    """Reserved backup — not required for v0 ship."""

    name = "brave"

    async def search(self, query: str, count: int) -> list[Candidate]:
        raise NotImplementedError("Brave discover adapter is a stub in v0")
