import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker import run_local, run_worker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Muvion Audience Pulse")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--worker", action="store_true", help="Consume analysis jobs from Redis"
    )
    mode.add_argument(
        "--run-id",
        type=uuid.UUID,
        help="Analyze one completed collection run directly",
    )
    parser.add_argument(
        "--analysis-run-id",
        type=uuid.UUID,
        help="Resume a specific analysis run (requires --run-id)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Consume at most one Redis batch and exit (requires --worker)",
    )
    args = parser.parse_args()
    if args.once and not args.worker:
        parser.error("--once requires --worker")
    if args.analysis_run_id and not args.run_id:
        parser.error("--analysis-run-id requires --run-id")
    return args


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if args.worker:
        await run_worker(settings, once=args.once)
        return
    analysis_run_id = await run_local(
        settings,
        collection_run_id=args.run_id,
        analysis_run_id=args.analysis_run_id,
    )
    print(f"Analysis completed: {analysis_run_id}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
