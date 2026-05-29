"""Verify Phase 1 database schema. Run: python -m scripts.verify_schema"""
import asyncio
import sys

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

REQUIRED_TABLES = [
    "companies",
    "users",
    "roles",
    "clients",
    "leads",
    "projects",
    "tasks",
    "invoices",
    "whatsapp_logs",
    "subscription_plans",
]

REQUIRED_INDEXES = [
    "idx_companies_slug_search",
    "idx_users_multi_tenant",
    "idx_leads_pipeline_filter",
    "idx_invoices_lookup",
    "idx_tasks_project_execution",
]

EXTRA_TABLES = ["password_reset_tokens", "alembic_version"]


async def verify() -> int:
    errors: list[str] = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        )
        tables = {row[0] for row in result.fetchall()}

        for name in REQUIRED_TABLES:
            if name not in tables:
                errors.append(f"Missing table: {name}")

        index_result = await db.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' ORDER BY indexname"
            )
        )
        indexes = {row[0] for row in index_result.fetchall()}

        for name in REQUIRED_INDEXES:
            if name not in indexes:
                errors.append(f"Missing index: {name}")

        version = await db.execute(text("SELECT version_num FROM alembic_version"))
        alembic_ver = version.scalar_one_or_none()

    print("=== AgencyFlow schema verification ===\n")
    print(f"Production tables ({len(REQUIRED_TABLES)}): OK" if not errors else "")
    for t in REQUIRED_TABLES:
        status = "OK" if t in tables else "MISSING"
        print(f"  [{status}] {t}")

    print("\nExtra tables:")
    for t in sorted(tables):
        if t in EXTRA_TABLES or t == "password_reset_tokens":
            print(f"  [OK] {t}")

    print("\nIndexes:")
    for idx in REQUIRED_INDEXES:
        status = "OK" if idx in indexes else "MISSING"
        print(f"  [{status}] {idx}")

    print(f"\nAlembic version: {alembic_ver}")

    if errors:
        print("\nFAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(verify()))
