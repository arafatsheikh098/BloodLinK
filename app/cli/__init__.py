"""Coordinator CLI: create-coordinator, seed, purge."""
from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.db import init_db
from app.seed import seed_demo


def cmd_create_coordinator(args: argparse.Namespace) -> int:
    """Create a coordinator account."""
    from sqlmodel import Session, select

    from app.db import get_engine
    from app.models.coordinator import Coordinator
    from app.security import hash_password

    init_db()
    username = args.username.strip()
    if not username:
        print("error: username is required", file=sys.stderr)
        return 2
    with Session(get_engine()) as session:
        existing = session.exec(
            select(Coordinator).where(Coordinator.username == username)
        ).first()
        if existing:
            print(f"coordinator {username!r} already exists (id={existing.id})")
            return 1
        coord = Coordinator(username=username, password_hash=hash_password(args.password))
        session.add(coord)
        session.commit()
        print(f"created coordinator {username!r} (id={coord.id})")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    seed_demo()
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    from app.purge import purge_old_requests
    cutoff_days = args.days if args.days is not None else get_settings().retention_days
    n = purge_old_requests(retention_days=cutoff_days)
    print(f"purged PII from {n} closed request(s) older than {cutoff_days} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("create-coordinator", help="Create a coordinator account")
    p1.add_argument("username")
    p1.add_argument("password")
    p1.set_defaults(func=cmd_create_coordinator)

    p2 = sub.add_parser("seed", help="Idempotent demo seed (fake data only)")
    p2.set_defaults(func=cmd_seed)

    p3 = sub.add_parser("purge", help="Purge requester PII from closed requests")
    p3.add_argument(
        "--days", type=int, default=None, help="override RETENTION_DAYS for this run"
    )
    p3.set_defaults(func=cmd_purge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
