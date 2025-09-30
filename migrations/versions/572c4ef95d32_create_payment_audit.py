"""create payment_audit

Revision ID: 572c4ef95d32
Revises: 0bf163bfa91e
Create Date: 2025-09-28
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '572c4ef95d32'
down_revision = '0bf163bfa91e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), nullable=False, index=True),
        sa.Column('borrower_id', sa.Integer(), nullable=False, index=True),
        sa.Column('repayment_id', sa.Integer(), sa.ForeignKey('repayments.id')),
        sa.Column('status', sa.String(32), nullable=False),  # e.g. OK / SUSPECT
        sa.Column('reason', sa.String(255)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('ix_pa_gid_borrower_status', 'payment_audit', ['group_id','borrower_id','status'])
    op.create_index('ix_pa_gid_status_created', 'payment_audit', ['group_id','status','created_at'])


def downgrade():
    op.drop_index('ix_pa_gid_status_created', table_name='payment_audit')
    op.drop_index('ix_pa_gid_borrower_status', table_name='payment_audit')
    op.drop_table('payment_audit')
