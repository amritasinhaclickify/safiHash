"""add outbox_transfers table

Revision ID: 5856990c3664
Revises: 1d3ac1089dfc
Create Date: 2025-10-13 19:04:59.812777

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '5856990c3664'
down_revision = '1d3ac1089dfc'
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    inspector = inspect(bind)
    return name in inspector.get_table_names()


def _drop_all_foreign_keys_for_table(bind, table_name, batch_op):
    """
    Drop all foreign keys on the given table by name (best-effort).
    This avoids calling drop_constraint(None, ...) which raises ValueError.
    """
    inspector = inspect(bind)
    try:
        fks = inspector.get_foreign_keys(table_name)
    except Exception:
        fks = []
    for fk in fks:
        fk_name = fk.get("name")
        if fk_name:
            try:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            except Exception:
                # best-effort: ignore if we can't drop it
                pass


def upgrade():
    bind = op.get_bind()

    # create outbox_transfers if missing
    if not _table_exists(bind, 'outbox_transfers'):
        op.create_table(
            'outbox_transfers',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('sender_id', sa.Integer(), nullable=False),
            sa.Column('recipient_id', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('asset_type', sa.String(length=16), nullable=False),
            sa.Column('token_id', sa.String(length=64), nullable=True),
            sa.Column('purpose', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False),
            sa.Column('attempts', sa.Integer(), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('hedera_tx_id', sa.String(length=255), nullable=True),
            sa.Column('hedera_path', sa.Text(), nullable=True),
            sa.Column('meta', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['recipient_id'], ['users.id']),
            sa.ForeignKeyConstraint(['sender_id'], ['users.id']),
        )

    # create outbox_attempts if missing
    if not _table_exists(bind, 'outbox_attempts'):
        op.create_table(
            'outbox_attempts',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('outbox_id', sa.Integer(), nullable=False),
            sa.Column('attempt_at', sa.DateTime(), nullable=False),
            sa.Column('success', sa.Boolean(), nullable=False),
            sa.Column('hedera_tx_id', sa.String(length=255), nullable=True),
            sa.Column('response', sa.Text(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['outbox_id'], ['outbox_transfers.id']),
        )

    # try to drop temp table if present
    if _table_exists(bind, '_alembic_tmp_member_balances'):
        try:
            op.drop_table('_alembic_tmp_member_balances')
        except Exception:
            pass

    # Safely alter repayments: drop any named fks first, then create a named fk
    if _table_exists(bind, 'repayments'):
        with op.batch_alter_table('repayments', schema=None) as batch_op:
            try:
                _drop_all_foreign_keys_for_table(bind, 'repayments', batch_op)
            except Exception:
                pass
            # create named fk to loans.loan_id -> loans.id if loans exists
            try:
                fk_name = batch_op.f('fk_repayments_loan_id_loans')
                batch_op.create_foreign_key(fk_name, 'loans', ['loan_id'], ['id'])
            except Exception:
                # ignore if loans table missing or FK creation fails
                pass

    # Safely alter trust_scores: create FK to users(user_id) if possible
    if _table_exists(bind, 'trust_scores'):
        with op.batch_alter_table('trust_scores', schema=None) as batch_op:
            try:
                _drop_all_foreign_keys_for_table(bind, 'trust_scores', batch_op)
            except Exception:
                pass
            try:
                fk_name = batch_op.f('fk_trust_scores_user_id_users')
                batch_op.create_foreign_key(fk_name, 'users', ['user_id'], ['id'])
            except Exception:
                pass


def downgrade():
    bind = op.get_bind()

    # Reverse trust_scores FK
    if _table_exists(bind, 'trust_scores'):
        with op.batch_alter_table('trust_scores', schema=None) as batch_op:
            try:
                _drop_all_foreign_keys_for_table(bind, 'trust_scores', batch_op)
            except Exception:
                pass

    # Reverse repayments FK
    if _table_exists(bind, 'repayments'):
        with op.batch_alter_table('repayments', schema=None) as batch_op:
            try:
                _drop_all_foreign_keys_for_table(bind, 'repayments', batch_op)
            except Exception:
                pass
            try:
                fk_name = batch_op.f('fk_repayments_loan_id_loan_requests')
                batch_op.create_foreign_key(fk_name, 'loan_requests', ['loan_id'], ['id'])
            except Exception:
                pass

    # recreate temp table if missing (best-effort)
    if not _table_exists(bind, '_alembic_tmp_member_balances'):
        try:
            op.create_table('_alembic_tmp_member_balances',
                sa.Column('id', sa.INTEGER(), nullable=False),
                sa.Column('group_id', sa.INTEGER(), nullable=False),
                sa.Column('user_id', sa.INTEGER(), nullable=False),
                sa.Column('total_deposit', sa.FLOAT(), nullable=False),
                sa.Column('interest_earned', sa.NUMERIC(precision=18, scale=2), nullable=False),
                sa.Column('total_withdrawn', sa.NUMERIC(precision=18, scale=2), nullable=False),
                sa.Column('created_at', sa.DATETIME(), nullable=False),
                sa.Column('updated_at', sa.DATETIME(), nullable=False),
                sa.Column('last_profit_share_at', sa.DATETIME(), nullable=True),
                sa.ForeignKeyConstraint(['group_id'], ['cooperative_groups.id']),
                sa.ForeignKeyConstraint(['user_id'], ['users.id']),
                sa.PrimaryKeyConstraint('id'),
                sa.UniqueConstraint('group_id', 'user_id', name=op.f('uq_group_user_balance'))
            )
        except Exception:
            pass

    # drop outbox tables if present
    if _table_exists(bind, 'outbox_attempts'):
        try:
            op.drop_table('outbox_attempts')
        except Exception:
            pass
    if _table_exists(bind, 'outbox_transfers'):
        try:
            op.drop_table('outbox_transfers')
        except Exception:
            pass
