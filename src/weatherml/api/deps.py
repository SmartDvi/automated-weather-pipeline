from collections.abc import Iterator

from sqlalchemy.orm import Session

from weatherml.db.session import session_scope


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session
