"""add created_at to voting_sessions

Revision ID: ab1f4742d9ce
Revises: 5a3819986225
Create Date: 2025-09-27 23:54:38.351932
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ab1f4742d9ce'
down_revision = '5a3819986225'
branch_labels = None
depends_on = None

def upgrade():
    # 1) add the column (nullable so it works on existing rows)
    op.add_column('voting_sessions', sa.Column('created_at', sa.DateTime(), nullable=True))

    # 2) backfill from loan_requests.created_at, else fallback to closed_at, else now()
    op.execute(sa.text("""
        UPDATE voting_sessions AS vs
        SET created_at = COALESCE(
            (SELECT lr.created_at FROM loan_requests lr WHERE lr.id = vs.loan_request_id),
            vs.closed_at,
            CURRENT_TIMESTAMP
        )
        WHERE vs.created_at IS NULL
    """))

def downgrade():
    op.drop_column('voting_sessions', 'created_at')
