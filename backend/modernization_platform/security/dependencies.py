"""FastAPI dependencies that authenticate credentials and resolve database roles."""

import logging
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.exceptions import UnauthorizedException
from modernization_platform.db.session import get_db_session
from modernization_platform.repositories.identities import IdentityRepository
from modernization_platform.security.authentication import JWTAuthenticator
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)

_BEARER = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal:
    """Authenticate a bearer token and load current roles from PostgreSQL."""
    try:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise UnauthorizedException()
        verified = JWTAuthenticator(settings).validate(credentials.credentials)
        principal = await IdentityRepository(session).resolve_principal(verified)
        if principal is None:
            raise UnauthorizedException()
        logger.info(
            "Authentication succeeded | user_id=%s tenant_id=%s method=%s",
            principal.user_id,
            principal.tenant_id,
            principal.authentication_method,
        )
        return principal
    except UnauthorizedException:
        logger.info("Authentication rejected")
        raise


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]

__all__ = ["CurrentPrincipal", "get_current_principal"]
