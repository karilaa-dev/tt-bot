"""Global queue manager for controlling concurrent operations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from data.config import config

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Singleton queue manager for controlling concurrent operations.

    Features:
    - Per-user tracking for info queue (limits concurrent requests per user)
    - Bypass option for inline downloads

    Usage:
        queue = QueueManager.get_instance()

        # For regular video downloads (with per-user limit):
        async with queue.info_queue(user_id) as acquired:
            if not acquired:
                # User limit exceeded, show error
                return
            video_info = await api.video_with_retry(...)

        # For inline downloads (bypass per-user limit):
        async with queue.info_queue(user_id, bypass_user_limit=True) as acquired:
            video_info = await api.video_with_retry(...)
    """

    _instance: QueueManager | None = None

    def __init__(self, max_user_queue: int):
        """
        Initialize the queue manager.

        Args:
            max_user_queue: Maximum videos per user in info queue
        """
        self.max_user_queue = max_user_queue
        self._user_info_counts: dict[int, int] = {}
        self._lock = asyncio.Lock()

        logger.info(f"QueueManager initialized: max_user_queue={max_user_queue}")

    @classmethod
    def get_instance(cls) -> QueueManager:
        """Get or create the singleton instance."""
        if cls._instance is None:
            queue_config = config["queue"]
            cls._instance = cls(
                max_user_queue=queue_config["max_user_queue_size"],
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None

    def get_user_queue_count(self, user_id: int) -> int:
        """Get current queue count for a user."""
        return self._user_info_counts.get(user_id, 0)

    async def acquire_info_for_user(
        self, user_id: int, bypass_user_limit: bool = False
    ) -> bool:
        """
        Acquire info slot for a user.

        Args:
            user_id: Telegram user/chat ID
            bypass_user_limit: If True, skip per-user limit check (for inline)

        Returns:
            True if acquired successfully, False if user limit exceeded
        """
        async with self._lock:
            if not bypass_user_limit:
                current_count = self._user_info_counts.get(user_id, 0)
                if current_count >= self.max_user_queue:
                    logger.debug(
                        f"User {user_id} rejected: {current_count}/{self.max_user_queue} in queue"
                    )
                    return False

            # Increment user count
            self._user_info_counts[user_id] = self._user_info_counts.get(user_id, 0) + 1

        logger.debug(
            f"User {user_id} acquired info slot "
            f"(user_count={self._user_info_counts.get(user_id, 0)})"
        )
        return True

    async def release_info_for_user(self, user_id: int) -> None:
        """Release info slot for a user.

        This method is async to properly acquire the lock and prevent
        race conditions when multiple coroutines release concurrently.
        """
        async with self._lock:
            if user_id in self._user_info_counts:
                self._user_info_counts[user_id] -= 1
                if self._user_info_counts[user_id] <= 0:
                    del self._user_info_counts[user_id]

        logger.debug(
            f"User {user_id} released info slot "
            f"(user_count={self._user_info_counts.get(user_id, 0)})"
        )

    @asynccontextmanager
    async def info_queue(
        self, user_id: int, bypass_user_limit: bool = False
    ) -> AsyncGenerator[bool, None]:
        """
        Context manager for info queue with per-user limiting.

        Args:
            user_id: Telegram user/chat ID
            bypass_user_limit: If True, skip per-user limit check (for inline)

        Yields:
            True if acquired successfully, False if user limit exceeded

        Usage:
            async with queue.info_queue(user_id) as acquired:
                if not acquired:
                    await message.reply("Queue full, please wait...")
                    return
                # Do work...
        """
        acquired = await self.acquire_info_for_user(user_id, bypass_user_limit)
        try:
            yield acquired
        finally:
            if acquired:
                await self.release_info_for_user(user_id)

    @property
    def active_users_count(self) -> int:
        """Number of users currently with items in the info queue."""
        return len(self._user_info_counts)
