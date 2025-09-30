"""Add unique constraint to mpesa_number in PaymentConfig (SQLite-safe)

Revision ID: 5a3819986225
Revises: dec2f9b92e4f
Create Date: 2025-09-25 06:52:36.562821
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5a3819986225"
down_revision = "dec2f9b92e4f"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1) guard: ensure no duplicate mpesa_number exists
    duplicates = conn.execute(
        sa.text(
            """
            SELECT mpesa_number, COUNT(*) AS cnt
            FROM payment_config
            WHERE mpesa_number IS NOT NULL
            GROUP BY mpesa_number
            HAVING cnt > 1
            """
        )
    ).fetchall()

    if duplicates:
        dup_list = ", ".join([f"{row[0]}({row[1]})" for row in duplicates])
        raise RuntimeError(
            "Cannot create UNIQUE constraint: duplicate mpesa_number values exist: "
            + dup_list
        )

    # 2) Use batch_alter_table (recreate table under-the-hood) to add unique constraint
    with op.batch_alter_table("payment_config", schema=None) as batch_op:
        # ensure column type/nullable matches model (safe no-op if identical)
        batch_op.alter_column(
            "mpesa_number",
            existing_type=sa.String(length=32),
            nullable=True,
        )
        # create named unique constraint (SQLite will perform recreate-copy-rename)
        batch_op.create_unique_constraint(
            "uq_payment_config_mpesa_number",
            ["mpesa_number"],
        )


def downgrade():
    # drop the unique constraint (again via batch)
    with op.batch_alter_table("payment_config", schema=None) as batch_op:
        batch_op.drop_constraint("uq_payment_config_mpesa_number", type_="unique")
