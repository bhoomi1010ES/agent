"""Test repository for managing characterization test cases and verification results."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.test_case import TestCase
from modernization_platform.db.models.test_result import TestResult
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class TestRepository(BaseRepository[TestCase]):
    """Repository operations for TestCase and TestResult entities."""

    __test__ = False

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_test_case(
        self,
        job_id: uuid.UUID,
        suite_version: int,
        layer: str,
        legacy_capture_ref: str,
        module_name: str | None = None,
        normalization_rule_ids: list[str] | None = None,
        captured_from: str = "legacy_run",
        test_case_id: uuid.UUID | None = None,
    ) -> TestCase:
        """Create and freeze a new characterization test case."""
        try:
            test_case = TestCase(
                id=test_case_id or uuid.uuid4(),
                job_id=job_id,
                suite_version=suite_version,
                layer=layer,
                module_name=module_name,
                legacy_capture_ref=legacy_capture_ref,
                normalization_rule_ids=normalization_rule_ids or [],
                captured_from=captured_from,
            )
            self.session.add(test_case)
            await self.session.flush()
            return test_case
        except Exception as exc:
            raise self._translate_error("create_test_case", exc) from exc

    async def get_test_case_by_id(self, test_case_id: uuid.UUID) -> TestCase | None:
        """Retrieve a test case by identifier."""
        try:
            stmt = select(TestCase).where(TestCase.id == test_case_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_test_case_by_id", exc) from exc

    async def list_test_cases_by_job(
        self,
        job_id: uuid.UUID,
        suite_version: int | None = None,
        module_name: str | None = None,
    ) -> list[TestCase]:
        """List test cases for a job, optionally filtered by suite version and module."""
        try:
            stmt = (
                select(TestCase)
                .where(TestCase.job_id == job_id)
                .order_by(TestCase.created_at.asc())
            )
            if suite_version is not None:
                stmt = stmt.where(TestCase.suite_version == suite_version)
            if module_name is not None:
                stmt = stmt.where(TestCase.module_name == module_name)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_test_cases_by_job", exc) from exc

    async def record_test_result(
        self,
        test_case_id: uuid.UUID,
        system: str,
        outcome: str,
        run_id: uuid.UUID | None = None,
        diff_summary: str | None = None,
        failure_class: str | None = None,
        result_id: uuid.UUID | None = None,
    ) -> TestResult:
        """Record an execution result for a test case."""
        try:
            res = TestResult(
                id=result_id or uuid.uuid4(),
                test_case_id=test_case_id,
                system=system,
                run_id=run_id,
                outcome=outcome,
                diff_summary=diff_summary,
                failure_class=failure_class,
            )
            self.session.add(res)
            await self.session.flush()
            return res
        except Exception as exc:
            raise self._translate_error("record_test_result", exc) from exc

    async def list_results_by_test_case(self, test_case_id: uuid.UUID) -> list[TestResult]:
        """List verification results for a specific test case."""
        try:
            stmt = (
                select(TestResult)
                .where(TestResult.test_case_id == test_case_id)
                .order_by(TestResult.executed_at.desc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_results_by_test_case", exc) from exc
