"""개발자용 사용자 관리 명령.

HTTP API로 역할을 만들거나 바꾸지 않는다. 실제 인증 연동 전까지 사용자는 이 명령이나
배포 환경의 동등한 관리 절차로만 관리한다.
"""

from __future__ import annotations

import argparse
import os

from h12.domain.workflow import Role, User
from h12.infra import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="h12 개발자용 사용자 관리")
    parser.add_argument("--database-url", default=os.getenv("H12_DATABASE_URL", "sqlite:///h12.db"))
    subcommands = parser.add_subparsers(dest="command", required=True)
    add = subcommands.add_parser("upsert", help="사용자를 생성하거나 역할·부서를 갱신한다")
    add.add_argument("--id", required=True)
    add.add_argument("--role", choices=[role.value for role in Role], required=True)
    add.add_argument("--department", required=True)
    args = parser.parse_args()

    database = Database(args.database_url)
    database.create_all()
    with database.work() as work:
        work.save_user(User(args.id, Role(args.role), args.department))


if __name__ == "__main__":
    main()
