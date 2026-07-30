import sys
import os
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cmd_run(args):
    from server.app import app
    from server.database import init_db, close_db
    from server.config import ServerConfig
    import uvicorn

    cfg = ServerConfig.load()
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(init_db(db_path))

        from server.mc.registry import migrate_instances_from_json
        migrate_instances_from_json()

        uvicorn_config = uvicorn.Config(
            app,
            host=args.host or cfg.host,
            port=args.port or cfg.port,
            log_level=args.log_level or cfg.log_level,
            loop="asyncio",
        )
        server = uvicorn.Server(uvicorn_config)
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(close_db())
        loop.close()


async def _list_projects():
    from server.database import get_session
    from server.models import ProjectModel
    from sqlalchemy import select
    async with get_session() as session:
        stmt = select(ProjectModel).order_by(ProjectModel.name)
        result = await session.execute(stmt)
        projects = result.scalars().all()
        if not projects:
            print("No projects configured")
            return
        print(f"Projects ({len(projects)}):")
        print(f"{'ID':<20} {'Name':<30} {'MC'}")
        print("-" * 70)
        for p in projects:
            print(f"{p.id:<20} {p.name:<30}")


def cmd_projects_list(args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_list_projects())
    finally:
        loop.close()


def main():
    parser = argparse.ArgumentParser(description="Uroboros Server")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run server (auth + API + admin)")
    p_run.add_argument("--host", default=None)
    p_run.add_argument("--port", type=int, default=None)
    p_run.add_argument("--log-level", default=None,
                       choices=["critical", "error", "warning", "info", "debug"])
    p_run.set_defaults(func=cmd_run)

    p_projects = sub.add_parser("projects", help="List projects")
    p_projects.set_defaults(func=cmd_projects_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
