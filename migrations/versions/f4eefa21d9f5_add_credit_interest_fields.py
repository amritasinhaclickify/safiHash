"""add credit interest fields

Revision ID: f4eefa21d9f5
Revises: 039032874164
Create Date: 2025-09-06 13:51:23.289702

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4eefa21d9f5'
down_revision = '039032874164'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('credit_ledger', sa.Column('interest_earned', sa.Numeric(18,2), nullable=False, server_default='0'))
    op.add_column('credit_ledger', sa.Column('last_interest_calc', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('credit_ledger', 'last_interest_calc')
    op.drop_column('credit_ledger', 'interest_earned')

