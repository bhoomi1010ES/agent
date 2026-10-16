"""Security policy enforcing SSRF prevention, URL validation, and host allowlists for Git operations."""

import ipaddress
import logging
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from modernization_platform.core.decorators import log_errors
from modernization_platform.integrations.git.errors import (
    InvalidRepositoryURLError,
    PrivateNetworkAccessError,
    RepositoryHostNotAllowedError,
)

logger = logging.getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_CLOUD_METADATA_IPS = {
    "169.254.169.254",  # AWS / GCP / Azure metadata endpoint
    "fd00:ec2::254",  # AWS IPv6 IMDS
    "100.100.100.200",  # Alibaba Cloud metadata
}


class GitSecurityPolicy:
    """Enforces network security, host allowlists, and protocol boundaries for Git remotes."""

    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        allow_private_ips_for_testing: bool = False,
    ) -> None:
        self._allowed_hosts = [h.strip().lower() for h in (allowed_hosts or []) if h.strip()]
        self._allow_private_ips = allow_private_ips_for_testing

    @property
    def allowed_hosts(self) -> list[str]:
        return list(self._allowed_hosts)

    @log_errors
    def validate_url(self, raw_url: str) -> str:
        """Validate repository URL against security invariants and return normalized URL.

        Raises:
            InvalidRepositoryURLError: on malformed URL, unsupported scheme, or embedded credentials.
            RepositoryHostNotAllowedError: if host is not permitted by allowlist.
            PrivateNetworkAccessError: if resolved IP violates private-network/SSRF boundaries.
        """
        if not raw_url or not raw_url.strip():
            raise InvalidRepositoryURLError("Repository URL cannot be empty.")

        url = raw_url.strip()
        if len(url) > 2048:
            raise InvalidRepositoryURLError(
                "Repository URL exceeds maximum length of 2048 characters."
            )

        if _CONTROL_CHARS.search(url):
            raise InvalidRepositoryURLError("Repository URL contains forbidden control characters.")

        try:
            parsed = urlsplit(url)
        except Exception as exc:
            raise InvalidRepositoryURLError(f"Failed to parse repository URL: {exc}") from exc

        # 1. Scheme enforcement: strictly HTTPS
        if parsed.scheme.lower() != "https":
            raise InvalidRepositoryURLError(
                f"Unsupported URL scheme '{parsed.scheme}'. Only HTTPS is permitted for Git remotes."
            )

        # 2. Credential embedding rejection: credentials must NOT be in the URL
        if parsed.username or parsed.password:
            raise InvalidRepositoryURLError(
                "Embedded userinfo or credentials in repository URLs are strictly forbidden."
            )

        # 3. Hostname validation
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise InvalidRepositoryURLError("Repository URL must specify a valid hostname.")

        # Reject local shorthand, localhost, or explicit raw IP literals unless in testing mode
        if (
            hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}  # nosec B104 - SSRF protection blocklist
            and not self._allow_private_ips
        ):
            raise PrivateNetworkAccessError(
                f"Access to loopback target '{hostname}' is strictly prohibited."
            )

        # 4. Host allowlist check (if allowlist configured)
        if self._allowed_hosts:
            host_matched = any(
                hostname == allowed or hostname.endswith(f".{allowed}")
                for allowed in self._allowed_hosts
            )
            if not host_matched:
                raise RepositoryHostNotAllowedError(
                    f"Host '{hostname}' is not in the permitted Git hosts allowlist: {self._allowed_hosts}."
                )

        # 5. DNS resolution and SSRF address validation
        if not self._allow_private_ips:
            self._verify_host_addresses(hostname)

        # 6. Normalize URL path: strip trailing slash, ensure lowercase scheme/host
        clean_path = parsed.path.rstrip("/")
        if not clean_path:
            raise InvalidRepositoryURLError("Repository URL must include a repository path.")

        return urlunsplit(
            (
                "https",
                f"{hostname}:{parsed.port}" if parsed.port else hostname,
                clean_path,
                parsed.query,
                "",  # fragment stripped
            )
        )

    @log_errors
    def _verify_host_addresses(self, hostname: str) -> None:
        """Resolve DNS and assert that resolved IPs do not target internal/private subnets."""
        try:
            addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise InvalidRepositoryURLError(
                f"Failed to resolve Git remote hostname '{hostname}': {exc}"
            ) from exc

        if not addr_info:
            raise InvalidRepositoryURLError(f"No IP addresses resolved for hostname '{hostname}'.")

        for item in addr_info:
            sockaddr = item[4]
            ip_str = sockaddr[0]

            if ip_str in _CLOUD_METADATA_IPS:
                logger.warning(
                    "SSRF blocked: host '%s' resolved to cloud metadata IP '%s'", hostname, ip_str
                )
                raise PrivateNetworkAccessError(
                    f"Host '{hostname}' resolved to prohibited cloud metadata address '{ip_str}'."
                )

            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            if (
                ip_obj.is_loopback
                or ip_obj.is_private
                or ip_obj.is_link_local
                or ip_obj.is_unspecified
                or ip_obj.is_multicast
                or ip_obj.is_reserved
            ):
                logger.warning(
                    "SSRF blocked: host '%s' resolved to prohibited private/local IP '%s'",
                    hostname,
                    ip_str,
                )
                raise PrivateNetworkAccessError(
                    f"Host '{hostname}' resolved to prohibited non-routable address '{ip_str}'."
                )


__all__ = ["GitSecurityPolicy"]
