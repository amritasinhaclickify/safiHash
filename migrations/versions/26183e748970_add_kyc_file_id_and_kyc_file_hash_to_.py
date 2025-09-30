"""Add kyc_file_id and kyc_file_hash to User

Revision ID: 26183e748970
Revises: ef74861b454c
Create Date: 2025-09-09 12:32:53.857262

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '26183e748970'
down_revision = 'ef74861b454c'
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Only add new columns to users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kyc_file_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('kyc_file_hash', sa.String(length=128), nullable=True))


def downgrade():
    # ✅ Only drop the columns if rollback happens
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('kyc_file_hash')
        batch_op.drop_column('kyc_file_id')
