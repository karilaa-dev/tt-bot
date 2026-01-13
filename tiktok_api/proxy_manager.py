"""Proxy manager with round-robin load balancing."""

import logging
import os
import re
import threading
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class ProxyManager:
    """Thread-safe round-robin proxy manager.

    Loads proxies from a file and rotates through them for each request.
    Optionally includes direct host connection (None) in rotation.

    File format: one proxy URL per line (http://, https://, socks5://)
    Lines starting with # are ignored (comments)
    Empty lines are ignored

    Example:
        >>> manager = ProxyManager("proxies.txt", include_host=True)
        >>> manager.get_next_proxy()  # Returns "http://proxy1:8080"
        >>> manager.get_next_proxy()  # Returns "http://proxy2:8080"
        >>> manager.get_next_proxy()  # Returns None (direct connection)
    """

    _instance: Optional["ProxyManager"] = None
    _lock = threading.Lock()

    def __init__(self, proxy_file: str, include_host: bool = False):
        """Initialize proxy manager.

        Args:
            proxy_file: Path to file containing proxy URLs (one per line)
            include_host: If True, include None (direct connection) in rotation
        """
        self._proxies: list[str | None] = []
        self._index = 0
        self._rotation_lock = threading.Lock()
        self._load_proxies(proxy_file, include_host)

    def _encode_proxy_auth(self, proxy_url: str) -> str:
        """URL-encode username and password in proxy URL.

        Args:
            proxy_url: Proxy URL (e.g., http://user:pass@host:port)

        Returns:
            Proxy URL with encoded credentials
        """
        # Pattern to match proxy URL with auth: protocol://user:pass@host:port
        match = re.match(r"^(https?|socks5)://([^:@]+):([^@]+)@(.+)$", proxy_url)
        if match:
            protocol, username, password, host_port = match.groups()
            # URL-encode username and password (safe characters: unreserved chars per RFC 3986)
            encoded_username = quote(username, safe="")
            encoded_password = quote(password, safe="")
            return f"{protocol}://{encoded_username}:{encoded_password}@{host_port}"
        # No auth or invalid format, return as-is
        return proxy_url

    def _load_proxies(self, file_path: str, include_host: bool) -> None:
        """Load proxies from file.

        Args:
            file_path: Path to proxy file
            include_host: Whether to include direct connection in rotation
        """
        if not file_path:
            logger.warning("No proxy file specified")
            if include_host:
                self._proxies = [None]
            return

        # Handle relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        if not os.path.isfile(file_path):
            logger.error(f"Proxy file not found: {file_path}")
            if include_host:
                self._proxies = [None]
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    # URL-encode authentication credentials
                    encoded_proxy = self._encode_proxy_auth(line)
                    self._proxies.append(encoded_proxy)
        except Exception as e:
            logger.error(f"Failed to load proxy file {file_path}: {e}")

        # Add None for direct host connection if enabled
        if include_host:
            self._proxies.append(None)

        if not self._proxies:
            logger.warning("No proxies loaded, will use direct connection")
            self._proxies = [None]
        else:
            proxy_count = len(self._proxies)
            host_included = None in self._proxies
            logger.info(
                f"Loaded {proxy_count} proxy entries (include_host={host_included})"
            )

    def get_next_proxy(self) -> str | None:
        """Get next proxy in round-robin rotation.

        Returns:
            Proxy URL string, or None for direct connection.
        """
        with self._rotation_lock:
            if not self._proxies:
                return None
            proxy = self._proxies[self._index]
            self._index = (self._index + 1) % len(self._proxies)
            return proxy

    def get_proxy_count(self) -> int:
        """Get total number of proxies in rotation (including host if enabled)."""
        return len(self._proxies)

    def peek_current(self) -> str | None:
        """Peek at current proxy without rotating (for logging only).

        Returns:
            Current proxy URL that would be returned by get_next_proxy(),
            or None for direct connection.
        """
        with self._rotation_lock:
            if not self._proxies:
                return None
            return self._proxies[self._index]

    def has_proxies(self) -> bool:
        """Check if any proxies are configured (excluding direct connection)."""
        return any(p is not None for p in self._proxies)

    @classmethod
    def initialize(cls, proxy_file: str, include_host: bool = False) -> "ProxyManager":
        """Initialize the singleton instance.

        Should be called once at application startup.

        Args:
            proxy_file: Path to proxy file
            include_host: Whether to include direct connection in rotation

        Returns:
            The initialized ProxyManager instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(proxy_file, include_host)
            return cls._instance

    @classmethod
    def get_instance(cls) -> Optional["ProxyManager"]:
        """Get the singleton instance, or None if not initialized."""
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (mainly for testing)."""
        with cls._lock:
            cls._instance = None
