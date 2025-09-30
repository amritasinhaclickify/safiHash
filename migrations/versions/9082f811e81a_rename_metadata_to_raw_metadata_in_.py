"""rename metadata to raw_metadata in PaymentAudit

Revision ID: 9082f811e81a
Revises: f4eefa21d9f5
Create Date: 2025-09-06 17:36:58.420598
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = "9082f811e81a"
down_revision = "f4eefa21d9f5"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # If table doesn't exist, create it with raw_metadata column directly
    if "payment_audits" not in tables:
        op.create_table(
            "payment_audits",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("payment_id", sa.Integer, nullable=True),
            sa.Column("group_id", sa.Integer, nullable=True),
            sa.Column("loan_id", sa.Integer, nullable=True),
            sa.Column("payer_id", sa.Integer, nullable=True),
            sa.Column("borrower_id", sa.Integer, nullable=True),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("applied_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("reason", sa.String(255), nullable=True),
            sa.Column("raw_metadata", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        # done; nothing more to rename
        return

    # Table exists — check columns. If 'metadata' exists, rename it.
    cols = [c["name"] for c in inspector.get_columns("payment_audits")]

    if "metadata" in cols and "raw_metadata" not in cols:
        # Preferred: try ALTER COLUMN / rename via op.alter_column (depends on DB support)
        try:
            # For engines that support RENAME COLUMN (modern SQLite, Postgres, MySQL)
            op.alter_column("payment_audits", "metadata", new_column_name="raw_metadata")
        except Exception:
            # Fallback: use batch_alter_table (works with SQLite older versions)
            try:
                with op.batch_alter_table("payment_audits") as batch_op:
                    batch_op.alter_column("metadata", new_column_name="raw_metadata")
            except Exception:
                # Final fallback: add new column, copy data, drop old column
                op.add_column("payment_audits", sa.Column("raw_metadata", sa.Text))
                conn.execute(
                    text("UPDATE payment_audits SET raw_metadata = metadata WHERE raw_metadata IS NULL")
                )
                # Drop column: SQLite may not support drop_column directly in older versions; batch_alter_table can be used.
                try:
                    op.drop_column("payment_audits", "metadata")
                except Exception:
                    # Try batch to remove the column
                    with op.batch_alter_table("payment_audits") as batch_op:
                        batch_op.drop_column("metadata")


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "payment_audits" not in tables:
        return

    cols = [c["name"] for c in inspector.get_columns("payment_audits")]

    # if raw_metadata exists and metadata does not, try to restore old name
    if "raw_metadata" in cols and "metadata" not in cols:
        try:
            op.alter_column("payment_audits", "raw_metadata", new_column_name="metadata")
        except Exception:
            try:
                with op.batch_alter_table("payment_audits") as batch_op:
                    batch_op.alter_column("raw_metadata", new_column_name="metadata")
            except Exception:
                op.add_column("payment_audits", sa.Column("metadata", sa.Text))
                conn.execute(
                    text("UPDATE payment_audits SET metadata = raw_metadata WHERE metadata IS NULL")
                )
                try:
                    op.drop_column("payment_audits", "raw_metadata")
                except Exception:
                    with op.batch_alter_table("payment_audits") as batch_op:
                        batch_op.drop_column("raw_metadata")
