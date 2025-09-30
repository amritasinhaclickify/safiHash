"""add credit payment models

Revision ID: 039032874164
Revises: 3f4038e3f770
Create Date: 2025-09-06 13:07:45.093001

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '039032874164'
down_revision = '3f4038e3f770'
branch_labels = None
depends_on = None


def upgrade():
    # credit_ledger
    op.create_table(
        'credit_ledger',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('cooperative_groups.id'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('loan_id', sa.Integer(), sa.ForeignKey('loans.id'), nullable=True, index=True),
        sa.Column('amount', sa.Numeric(18,2), nullable=False, server_default='0'),
        sa.Column('source', sa.String(length=40), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('group_id', 'user_id', name='uq_group_user_credit')
    )
    op.create_index('ix_credit_group_user', 'credit_ledger', ['group_id', 'user_id'])

    # payment_audits
    op.create_table(
        'payment_audits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payment_id', sa.Integer(), nullable=True, index=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('cooperative_groups.id'), nullable=True, index=True),
        sa.Column('loan_id', sa.Integer(), sa.ForeignKey('loans.id'), nullable=True, index=True),
        sa.Column('payer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
        sa.Column('borrower_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
        sa.Column('amount', sa.Numeric(18,2), nullable=False),
        sa.Column('applied_amount', sa.Numeric(18,2), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('ix_audits_group_loan', 'payment_audits', ['group_id', 'loan_id'])

    # payment_approvals
    op.create_table(
        'payment_approvals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('repayment_id', sa.Integer(), sa.ForeignKey('repayments.id'), nullable=True, index=True),
        sa.Column('payer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('approver_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
        sa.Column('is_agent_payment', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('ix_approvals_payer', 'payment_approvals', ['payer_id'])


def downgrade():
    op.drop_index('ix_approvals_payer', table_name='payment_approvals')
    op.drop_index('ix_audits_group_loan', table_name='payment_audits')
    op.drop_index('ix_credit_group_user', table_name='credit_ledger')

    op.drop_table('payment_approvals')
    op.drop_table('payment_audits')
    op.drop_table('credit_ledger')
