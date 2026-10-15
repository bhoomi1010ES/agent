"""Unit tests verifying extension boundaries and package imports."""

import modernization_platform.db as db_pkg
import modernization_platform.domain as domain_pkg
import modernization_platform.integrations as integrations_pkg
import modernization_platform.observability as observability_pkg
import modernization_platform.repositories as repositories_pkg
import modernization_platform.schemas as schemas_pkg
import modernization_platform.security as security_pkg
import modernization_platform.services as services_pkg
import modernization_platform.storage as storage_pkg
import modernization_platform.workers as workers_pkg
import modernization_platform.workflows as workflows_pkg


def test_extension_boundary_packages_exist_and_import() -> None:
    """Verify all designated extension boundary packages import cleanly."""
    boundaries = [
        db_pkg,
        domain_pkg,
        integrations_pkg,
        observability_pkg,
        repositories_pkg,
        schemas_pkg,
        security_pkg,
        services_pkg,
        storage_pkg,
        workers_pkg,
        workflows_pkg,
    ]
    for pkg in boundaries:
        assert hasattr(pkg, "__all__")
        assert isinstance(pkg.__all__, list)
