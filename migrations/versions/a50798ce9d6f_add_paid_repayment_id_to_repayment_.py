"""add paid_repayment_id to repayment_schedules

Revision ID: a50798ce9d6f
Revises: ab1f4742d9ce
Create Date: 2025-09-28 02:00:51.633427

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a50798ce9d6f'
down_revision = 'ab1f4742d9ce'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('repayment_schedules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paid_repayment_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_repayment_schedules_paid_repayment',  # constraint ka naam zaroori hai
            'repayments',
            ['paid_repayment_id'],
            ['id'],
            ondelete="SET NULL"
        )

    # optional index for faster lookup
    op.create_index(
        'ix_repayment_schedules_paid_repayment_id',
        'repayment_schedules',
        ['paid_repayment_id']
    )


def downgrade():
    # drop FK + index + column
    with op.batch_alter_table('repayment_schedules', schema=None) as batch_op:
        batch_op.drop_constraint('fk_repayment_schedules_paid_repayment', type_='foreignkey')
        batch_op.drop_column('paid_repayment_id')

    op.drop_index('ix_repayment_schedules_paid_repayment_id', table_name='repayment_schedules')
