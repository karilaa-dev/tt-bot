"""Sequential per-user queue manager."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from data.config import config

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Sequential per-user queue with max depth.

    Each user's requests are processed one at a time (sequential).
    If user exceeds max_queue_size, new requests are rejected.

    Usage:
        queue = QueueManager.get_instance()

        async with queue.user_queue(user_id) as acquired:
            if not acquired:
                # Queue full, show error
                return
            # Process video (fetch + send) - next request waits
    """

    _instance: QueueManager | None = None

    def __init__(self, max_queue_size: int = 3):
        self.max_queue_size = max_queue_size
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._user_queue_counts: dict[int, int] = {}
        self._dict_lock = asyncio.Lock()  # Protects dicts

        logger.info(f"QueueManager initialized: max_queue_size={max_queue_size}")

    @classmethod
    def get_instance(cls) -> QueueManager:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(
                max_queue_size=config["queue"]["max_user_queue_size"],
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def get_user_queue_count(self, user_id: int) -> int:
        """Get current queue count for a user."""
        return self._user_queue_counts.get(user_id, 0)

    async def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Get or create lock for user."""
        async with self._dict_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    async def _increment_count(self, user_id: int) -> bool:
        """Increment queue count. Returns False if at max."""
        async with self._dict_lock:
            current = self._user_queue_counts.get(user_id, 0)
            if current >= self.max_queue_size:
                return False
            self._user_queue_counts[user_id] = current + 1
            logger.debug(f"User {user_id} queue: {current + 1}/{self.max_queue_size}")
            return True

    async def _decrement_count(self, user_id: int) -> None:
        """Decrement queue count and cleanup lock if no longer needed."""
        async with self._dict_lock:
            if user_id in self._user_queue_counts:
                self._user_queue_counts[user_id] -= 1
                if self._user_queue_counts[user_id] <= 0:
                    del self._user_queue_counts[user_id]
                    # Clean up lock when user has no active requests
                    # This prevents unbounded memory growth with many unique users
                    if user_id in self._user_locks:
                        del self._user_locks[user_id]
            logger.debug(
                f"User {user_id} queue: {self._user_queue_counts.get(user_id, 0)}/{self.max_queue_size}"
            )

    @asynccontextmanager
    async def user_queue(
        self, user_id: int, bypass: bool = False
    ) -> AsyncGenerator[bool, None]:
        """
        Sequential queue with max depth.

        Args:
            user_id: Telegram user/chat ID
            bypass: If True, skip queue entirely (for inline mode)

        Yields:
            True if acquired, False if queue full
        """
        if bypass:
            yield True
            return

        # Check if queue is full BEFORE waiting
        if not await self._increment_count(user_id):
            yield False  # Queue full
            return

        # Get user's lock and wait for turn
        lock = await self._get_user_lock(user_id)
        try:
            async with lock:
                yield True  # Acquired, process request
        finally:
            await self._decrement_count(user_id)

    @property
    def active_users_count(self) -> int:
        """Number of users with items in queue."""
        return len(self._user_queue_counts)
