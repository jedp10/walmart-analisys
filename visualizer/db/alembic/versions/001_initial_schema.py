"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
    )

    # workers
    op.create_table(
        "workers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "worker_type",
            sa.String(20),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("workers.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "worker_type IN ('merchandiser', 'supervisor')",
            name="ck_workers_worker_type",
        ),
    )

    # products
    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("upc", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.String(255)),
    )

    # stores
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("description", sa.String(255)),
        sa.Column("lat", sa.Numeric(10, 7)),
        sa.Column("lng", sa.Numeric(10, 7)),
    )

    # workers_x_stores
    op.create_table(
        "workers_x_stores",
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.Integer,
            sa.ForeignKey("workers.id"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("store_id", "worker_id"),
    )

    # daily_data
    op.create_table(
        "daily_data",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column(
            "product_id",
            sa.Integer,
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id"),
            nullable=False,
        ),
        sa.Column("so_units", sa.Integer),
        sa.Column("unit_cost", sa.Numeric(12, 2)),
        sa.Column("so_amount", sa.Numeric(12, 2)),
        sa.Column("inv_on_hand", sa.Integer),
        sa.Column("inv_in_transit", sa.Integer),
        sa.Column("inv_in_warehouse", sa.Integer),
        sa.Column("inv_on_order", sa.Integer),
        sa.Column("cataloged", sa.Boolean, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("date", "product_id", "store_id"),
    )

    # alarms
    op.create_table(
        "alarms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "product_id",
            sa.Integer,
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id"),
            nullable=False,
        ),
        sa.Column("alarm_type", sa.String(20), nullable=False),
        sa.Column("alarm_data", JSONB),
        sa.Column("ref_id", sa.Integer, nullable=True),
        sa.Column("status", sa.String(50)),
        sa.Column("status_reason", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "alarm_type IN ('overstock', 'dead_inventory', 'poor_display')",
            name="ck_alarms_alarm_type",
        ),
    )

    # alarm_actions
    op.create_table(
        "alarm_actions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "alarm_id",
            sa.Integer,
            sa.ForeignKey("alarms.id"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text),
        sa.Column("attachment", sa.String(500)),
        sa.Column(
            "worker_id",
            sa.Integer,
            sa.ForeignKey("workers.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
        sa.Column("metadata", JSONB),
    )

    # settings
    op.create_table(
        "settings",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", JSONB),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.text("NOW()")),
    )

    # Indices
    op.create_index(
        "ix_daily_data_product_store", "daily_data", ["product_id", "store_id"]
    )
    op.create_index("ix_daily_data_date", "daily_data", ["date"])
    op.create_index(
        "ix_alarms_product_store", "alarms", ["product_id", "store_id"]
    )
    op.create_index("ix_alarms_alarm_type", "alarms", ["alarm_type"])
    op.create_index("ix_alarms_status", "alarms", ["status"])
    op.create_index("ix_alarm_actions_alarm_id", "alarm_actions", ["alarm_id"])
    op.create_index("ix_products_upc", "products", ["upc"])


def downgrade() -> None:
    op.drop_index("ix_products_upc", table_name="products")
    op.drop_index("ix_alarm_actions_alarm_id", table_name="alarm_actions")
    op.drop_index("ix_alarms_status", table_name="alarms")
    op.drop_index("ix_alarms_alarm_type", table_name="alarms")
    op.drop_index("ix_alarms_product_store", table_name="alarms")
    op.drop_index("ix_daily_data_date", table_name="daily_data")
    op.drop_index("ix_daily_data_product_store", table_name="daily_data")

    op.drop_table("settings")
    op.drop_table("alarm_actions")
    op.drop_table("alarms")
    op.drop_table("daily_data")
    op.drop_table("workers_x_stores")
    op.drop_table("stores")
    op.drop_table("products")
    op.drop_table("workers")
    op.drop_table("users")
