"""Git integration, provider abstraction, security policy, and source provenance package."""

from modernization_platform.integrations.git.base import GitProvider
from modernization_platform.integrations.git.errors import (
    GitAuthenticationError,
    GitExecutionError,
    GitIntegrationError,
    GitRevisionNotFoundError,
    GitTimeoutError,
    InvalidRepositoryURLError,
    PrivateNetworkAccessError,
    RepositoryFileCountExceededError,
    RepositoryHostNotAllowedError,
    RepositorySizeExceededError,
)
from modernization_platform.integrations.git.models import (
    BranchConvention,
    GitCredentials,
    GitSourceReference,
    RepositoryMetadata,
    SourceProvenance,
    compute_provenance_hash,
)
from modernization_platform.integrations.git.policy import GitSecurityPolicy
from modernization_platform.integrations.git.providers.https_provider import HttpsGitProvider

__all__ = [
    "BranchConvention",
    "GitAuthenticationError",
    "GitCredentials",
    "GitExecutionError",
    "GitIntegrationError",
    "GitProvider",
    "GitRevisionNotFoundError",
    "GitSecurityPolicy",
    "GitSourceReference",
    "GitTimeoutError",
    "HttpsGitProvider",
    "InvalidRepositoryURLError",
    "PrivateNetworkAccessError",
    "RepositoryFileCountExceededError",
    "RepositoryHostNotAllowedError",
    "RepositoryMetadata",
    "RepositorySizeExceededError",
    "SourceProvenance",
    "compute_provenance_hash",
]
