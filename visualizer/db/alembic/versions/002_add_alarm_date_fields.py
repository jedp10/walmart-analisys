"""add started_at and finished_at to alarms

Revision ID: 002
Revises: 001
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alarms", sa.Column("started_at", sa.Date, nullable=False))
    op.add_column("alarms", sa.Column("finished_at", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("alarms", "finished_at")
    op.drop_column("alarms", "started_at")
