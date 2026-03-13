"""Service registry for mapping services to their clients and routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter

from .base_client import BaseClient


@dataclass
class ServiceEntry:
    """A registered scraper service."""

    name: str
    client: BaseClient
    router: APIRouter
    shutdown: Callable[[], Awaitable[None]] | None = None


class ServiceRegistry:
    """Registry of scraper services."""

    def __init__(self) -> None:
        self._services: dict[str, ServiceEntry] = {}

    def register(self, entry: ServiceEntry) -> None:
        self._services[entry.name] = entry

    def get(self, name: str) -> ServiceEntry | None:
        return self._services.get(name)

    def get_all(self) -> list[ServiceEntry]:
        return list(self._services.values())
