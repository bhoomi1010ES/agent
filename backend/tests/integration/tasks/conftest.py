"""Task integration test configuration.

Ensures WindowsSelectorEventLoopPolicy is applied on Windows for psycopg async compatibility
required by LangGraph AsyncPostgresSaver.
"""

import asyncio
import sys

import pytest

if sys.platform == "win32":

    @pytest.fixture(scope="session")
    def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
        """Use SelectorEventLoop on Windows for psycopg async compatibility."""
        return asyncio.WindowsSelectorEventLoopPolicy()
