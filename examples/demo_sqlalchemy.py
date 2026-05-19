"""Demo file exercising the SQLAlchemy 1.4 -> 2.0 plugin.

Run::

    pycomprepair scan examples/demo_sqlalchemy.py --target "sqlalchemy>=2.0"
    pycomprepair repair examples/demo_sqlalchemy.py --target "sqlalchemy>=2.0" --dry-run

Each block triggers a distinct rule from ``pycomprepair.plugins.sqlalchemy_v2``.
"""

from __future__ import annotations

# SQL001 — legacy declarative_base import path (auto-fixed).
from sqlalchemy.ext.declarative import declarative_base

# SQL003 — declarative_base() is legacy in 2.0; prefer ``DeclarativeBase``.
Base = declarative_base()


class User(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "users"


def fetch(session, pk):
    # SQL002 — auto-fixed to ``session.get(User, pk)``.
    return session.query(User).get(pk)


def deactivate_all(session):
    # SQL005 — informational note about ``synchronize_session`` default.
    return session.query(User).update({"active": False})


def purge(session):
    # SQL005 — same note for ``.delete()``.
    return session.query(User).delete()
