"""add profit sharing models and fields

Revision ID: 0442861af74e
Revises: 9082f811e81a
Create Date: 2025-09-07 12:15:01.341506
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '0442861af74e'
down_revision = '9082f811e81a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    # ---- Safe Table Create ----
    if "group_profit_pool" not in inspector.get_table_names():
        op.create_table(
            'group_profit_pool',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('group_id', sa.Integer(), nullable=False),
            sa.Column('accrued_interest', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('expenses', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('net_available', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('last_updated', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['group_id'], ['cooperative_groups.id'])
        )
        op.create_index('ix_group_profit_pool_group_id', 'group_profit_pool', ['group_id'])

    if "profit_distributions" not in inspector.get_table_names():
        op.create_table(
            'profit_distributions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('group_id', sa.Integer(), nullable=False),
            sa.Column('distributed_at', sa.DateTime(), nullable=False),
            sa.Column('total_distributed', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('reserve_amount', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('admin_amount', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('note', sa.String(255)),
            sa.ForeignKeyConstraint(['group_id'], ['cooperative_groups.id'])
        )
        op.create_index('ix_profit_distributions_group_id', 'profit_distributions', ['group_id'])
        op.create_index('ix_profit_distributions_distributed_at', 'profit_distributions', ['distributed_at'])

    if "profit_share_details" not in inspector.get_table_names():
        op.create_table(
            'profit_share_details',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('distribution_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(18, 2), nullable=False),
            sa.Column('deposit_snapshot', sa.Numeric(18, 2), nullable=False),
            sa.ForeignKeyConstraint(['distribution_id'], ['profit_distributions.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'])
        )
        op.create_index('ix_profit_share_details_distribution_id', 'profit_share_details', ['distribution_id'])
        op.create_index('ix_profit_share_details_user_id', 'profit_share_details', ['user_id'])

    if "credit_ledger" not in inspector.get_table_names():
        op.create_table(
            'credit_ledger',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('group_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('loan_id', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('interest_earned', sa.Numeric(18, 2), nullable=False, default=0),
            sa.Column('last_interest_calc', sa.DateTime(), nullable=True),
            sa.Column('source', sa.String(40)),
            sa.Column('note', sa.String(255)),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['group_id'], ['cooperative_groups.id']),
            sa.ForeignKeyConstraint(['loan_id'], ['loans.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.UniqueConstraint('group_id', 'user_id', name='uq_group_user_credit')
        )
        op.create_index('ix_credit_ledger_group_id', 'credit_ledger', ['group_id'])
        op.create_index('ix_credit_ledger_user_id', 'credit_ledger', ['user_id'])
        op.create_index('ix_credit_ledger_loan_id', 'credit_ledger', ['loan_id'])
        op.create_index('ix_credit_ledger_created_at', 'credit_ledger', ['created_at'])

    if "payment_approvals" not in inspector.get_table_names():
        op.create_table(
            'payment_approvals',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('repayment_id', sa.Integer(), nullable=True),
            sa.Column('payer_id', sa.Integer(), nullable=False),
            sa.Column('approver_id', sa.Integer(), nullable=True),
            sa.Column('is_agent_payment', sa.Boolean(), nullable=False, default=False),
            sa.Column('approved', sa.Boolean(), nullable=False, default=False),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('notes', sa.String(255)),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['repayment_id'], ['repayments.id']),
            sa.ForeignKeyConstraint(['payer_id'], ['users.id']),
            sa.ForeignKeyConstraint(['approver_id'], ['users.id'])
        )
        op.create_index('ix_payment_approvals_repayment_id', 'payment_approvals', ['repayment_id'])
        op.create_index('ix_payment_approvals_payer_id', 'payment_approvals', ['payer_id'])
        op.create_index('ix_payment_approvals_approver_id', 'payment_approvals', ['approver_id'])

    # ---- Safe Column Add ----
    existing_cols = [c['name'] for c in inspector.get_columns('cooperative_groups')]
    if "profit_reserve_pct" not in existing_cols:
        op.add_column('cooperative_groups', sa.Column('profit_reserve_pct', sa.Float(), nullable=True))
    if "admin_cut_pct" not in existing_cols:
        op.add_column('cooperative_groups', sa.Column('admin_cut_pct', sa.Float(), nullable=True))
    if "distribute_on_profit" not in existing_cols:
        op.add_column('cooperative_groups', sa.Column('distribute_on_profit', sa.Boolean(), nullable=False, server_default=sa.text("0")))
    if "last_profit_settlement" not in existing_cols:
        op.add_column('cooperative_groups', sa.Column('last_profit_settlement', sa.DateTime(), nullable=True))

    existing_cols = [c['name'] for c in inspector.get_columns('member_balances')]
    if "last_profit_share_at" not in existing_cols:
        op.add_column('member_balances', sa.Column('last_profit_share_at', sa.DateTime(), nullable=True))

    existing_cols = [c['name'] for c in inspector.get_columns('payment_audits')]
    if "metadata" not in existing_cols:
        op.add_column('payment_audits', sa.Column('metadata', sa.Text(), nullable=True))


def downgrade():
    # Downgrade simple drop
    op.drop_table('payment_approvals')
    op.drop_table('credit_ledger')
    op.drop_table('profit_share_details')
    op.drop_table('profit_distributions')
    op.drop_table('group_profit_pool')

    with op.batch_alter_table('cooperative_groups', schema=None) as batch_op:
        batch_op.drop_column('profit_reserve_pct')
        batch_op.drop_column('admin_cut_pct')
        batch_op.drop_column('distribute_on_profit')
        batch_op.drop_column('last_profit_settlement')

    with op.batch_alter_table('member_balances', schema=None) as batch_op:
        batch_op.drop_column('last_profit_share_at')

    with op.batch_alter_table('payment_audits', schema=None) as batch_op:
        batch_op.drop_column('metadata')
