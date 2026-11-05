"""Run the retry of file removal once and print the result.

    python -m app.cleanup

For deployments that prefer cron (or set ``FILE_CLEANUP_INTERVAL_SECONDS=0``) over the
in-process loop. Exit status is 0 when nothing is left pending, 1 otherwise.
"""

import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory
from app.services.file_cleanup import pending_summary, run_file_cleanup
from app.storage import create_storage


async def run() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.database_url is None:
        print("DATABASE_URL is not configured", file=sys.stderr)
        return 2
    engine = create_db_engine(settings.database_url)
    try:
        factory = create_session_factory(engine)
        report = await run_file_cleanup(factory, create_storage(settings))
        async with factory() as session:
            waiting, oldest = await pending_summary(session)
    finally:
        await engine.dispose()
    print(
        f"attempted={report.attempted} removed={report.removed} failed={report.failed} "
        f"still_pending={waiting} oldest={oldest.isoformat() if oldest else '-'}"
    )
    return 0 if waiting == 0 else 1


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
