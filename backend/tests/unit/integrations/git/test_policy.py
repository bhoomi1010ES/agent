"""Unit tests for GitSecurityPolicy enforcing SSRF prevention and allowlists."""

import socket
from unittest.mock import patch

import pytest

from modernization_platform.integrations.git.errors import (
    InvalidRepositoryURLError,
    PrivateNetworkAccessError,
    RepositoryHostNotAllowedError,
)
from modernization_platform.integrations.git.policy import GitSecurityPolicy


def test_valid_https_urls_accepted() -> None:
    policy = GitSecurityPolicy(allowed_hosts=["github.com", "gitlab.com"])
    normalized = policy.validate_url("https://github.com/acme/legacy-monolith.git")
    assert normalized == "https://github.com/acme/legacy-monolith.git"

    normalized_trailing = policy.validate_url("https://gitlab.com/group/project/")
    assert normalized_trailing == "https://gitlab.com/group/project"


def test_reject_unsupported_schemes() -> None:
    policy = GitSecurityPolicy()
    unsupported = [
        "http://github.com/acme/repo.git",
        "file:///tmp/repo.git",
        "git://github.com/acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "ftp://github.com/acme/repo.git",
    ]
    for url in unsupported:
        with pytest.raises(InvalidRepositoryURLError, match="Only HTTPS is permitted"):
            policy.validate_url(url)


def test_reject_embedded_credentials() -> None:
    policy = GitSecurityPolicy()
    credential_urls = [
        "https://token:secret@github.com/acme/repo.git",
        "https://user@github.com/acme/repo.git",
        "https://:password@github.com/acme/repo.git",
    ]
    for url in credential_urls:
        with pytest.raises(InvalidRepositoryURLError, match="Embedded userinfo or credentials"):
            policy.validate_url(url)


def test_reject_disallowed_hosts() -> None:
    policy = GitSecurityPolicy(allowed_hosts=["github.com", "gitlab.com"])
    with pytest.raises(
        RepositoryHostNotAllowedError, match="not in the permitted Git hosts allowlist"
    ):
        policy.validate_url("https://evil-untrusted-server.com/repo.git")


def test_reject_loopback_and_local_hosts() -> None:
    policy = GitSecurityPolicy(allow_private_ips_for_testing=False)
    local_targets = [
        "https://localhost/repo.git",
        "https://127.0.0.1/repo.git",
        "https://0.0.0.0/repo.git",
        "https://[::1]/repo.git",
    ]
    for url in local_targets:
        with pytest.raises(PrivateNetworkAccessError, match="prohibited"):
            policy.validate_url(url)


def test_reject_private_ip_resolution_ssrf() -> None:
    policy = GitSecurityPolicy(allowed_hosts=["fake-internal.corp"])

    # Simulate fake-internal.corp resolving to 10.0.0.5 (RFC 1918 private)
    with (
        patch("socket.getaddrinfo", return_value=[(socket.AF_INET, 0, 0, "", ("10.0.0.5", 443))]),
        pytest.raises(PrivateNetworkAccessError, match="prohibited non-routable address"),
    ):
        policy.validate_url("https://fake-internal.corp/repo.git")


def test_reject_cloud_metadata_ip_resolution() -> None:
    policy = GitSecurityPolicy(allowed_hosts=["metadata.local"])

    # Simulate host resolving to 169.254.169.254
    with (
        patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, 0, 0, "", ("169.254.169.254", 443))],
        ),
        pytest.raises(PrivateNetworkAccessError, match="cloud metadata address"),
    ):
        policy.validate_url("https://metadata.local/repo.git")


def test_allow_private_ips_when_testing_flag_is_true() -> None:
    policy = GitSecurityPolicy(allow_private_ips_for_testing=True)
    # Loopback target permitted when testing flag is enabled
    normalized = policy.validate_url("https://127.0.0.1:8443/test-repo.git")
    assert normalized == "https://127.0.0.1:8443/test-repo.git"


def test_reject_empty_or_control_chars() -> None:
    policy = GitSecurityPolicy()
    with pytest.raises(InvalidRepositoryURLError, match="cannot be empty"):
        policy.validate_url("")

    with pytest.raises(InvalidRepositoryURLError, match="control characters"):
        policy.validate_url("https://github.com/repo\x00malicious.git")
