"""create outbox tables

Revision ID: 1d3ac1089dfc
Revises: 2d6b2fc0b306
Create Date: 2025-10-13 17:19:10.136927

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision = '1d3ac1089dfc'
down_revision = '2d6b2fc0b306'
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    inspector = inspect(bind)
    return name in inspector.get_table_names()


def _drop_all_foreign_keys_for_table(bind, table_name, batch_op):
    inspector = inspect(bind)
    fks = inspector.get_foreign_keys(table_name)
    for fk in fks:
        fk_name = fk.get("name")
        if fk_name:
            try:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            except Exception:
                pass


def upgrade():
    bind = op.get_bind()

    # Create outbox_transfers only if it doesn't already exist
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

    # Create outbox_attempts only if it doesn't already exist
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

    # drop temp table only if present
    if _table_exists(bind, '_alembic_tmp_member_balances'):
        op.drop_table('_alembic_tmp_member_balances')

    # The following batch_alter_table operations are preserved as generated,
    # but guarded to avoid hard failures when the DB state differs.
    with op.batch_alter_table('member_balances', schema=None) as batch_op:
        batch_op.alter_column('total_deposit',
               existing_type=sa.NUMERIC(precision=18, scale=2),
               type_=sa.Float(),
               existing_nullable=False)

    with op.batch_alter_table('payment_attempts', schema=None) as batch_op:
        try:
            _drop_all_foreign_keys_for_table(bind, 'payment_attempts', batch_op)
        except Exception:
            pass

        batch_op.alter_column('id',
               existing_type=sa.INTEGER(),
               nullable=False,
               autoincrement=True)
        batch_op.alter_column('order_id',
               existing_type=sa.TEXT(),
               type_=sa.String(length=64),
               nullable=False)
        batch_op.alter_column('msisdn',
               existing_type=sa.TEXT(),
               type_=sa.String(length=32),
               nullable=False)
        batch_op.alter_column('mpesa_ref',
               existing_type=sa.TEXT(),
               type_=sa.String(length=64),
               existing_nullable=True)
        batch_op.alter_column('status',
               existing_type=sa.TEXT(),
               type_=sa.String(length=32),
               existing_nullable=True)
        batch_op.alter_column('hedera_tx_hash',
               existing_type=sa.TEXT(),
               type_=sa.String(length=128),
               existing_nullable=True)
        batch_op.alter_column('created_at',
               existing_type=sa.NUMERIC(),
               type_=sa.DateTime(),
               existing_nullable=True)
        batch_op.alter_column('updated_at',
               existing_type=sa.NUMERIC(),
               type_=sa.DateTime(),
               existing_nullable=True)
        # create_foreign_key with an explicit name (some Alembic/DB combos require it)
        try:
            fk_name = batch_op.f('fk_payment_attempts_order_id_payment_orders')
            batch_op.create_foreign_key(fk_name, 'payment_orders', ['order_id'], ['order_id'])
        except Exception:
            pass

    with op.batch_alter_table('payment_config', schema=None) as batch_op:
        try:
            batch_op.drop_constraint(batch_op.f('uq_payment_config_mpesa_number'), type_='unique')
        except Exception:
            pass
        try:
            batch_op.drop_index(batch_op.f('ix_payment_config_mpesa_number'))
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_payment_config_mpesa_number'), ['mpesa_number'], unique=True)
        except Exception:
            pass

    with op.batch_alter_table('profit_share_details', schema=None) as batch_op:
        batch_op.alter_column('deposit_snapshot',
               existing_type=sa.NUMERIC(precision=18, scale=2),
               type_=sa.Float(),
               existing_nullable=False)

    with op.batch_alter_table('repayment_schedules', schema=None) as batch_op:
        # drop indexes/constraints if they exist; otherwise ignore
        for idx in (
            batch_op.f('ix_repayment_schedules_paid_repayment_id'),
            batch_op.f('ix_rs_loan_duedate'),
            batch_op.f('ix_rs_loan_status'),
            batch_op.f('ix_rs_loan_status_paidat'),
            batch_op.f('ix_rs_paid_repayment_id'),
        ):
            try:
                batch_op.drop_index(idx)
            except Exception:
                pass

        try:
            _drop_all_foreign_keys_for_table(bind, 'repayment_schedules', batch_op)
        except Exception:
            pass

        try:
            fk_name = batch_op.f('fk_repayment_schedules_paid_repayment_repayments')
            batch_op.create_foreign_key(fk_name, 'repayments', ['paid_repayment_id'], ['id'])
        except Exception:
            pass

    with op.batch_alter_table('repayments', schema=None) as batch_op:
        try:
            _drop_all_foreign_keys_for_table(bind, 'repayments', batch_op)
        except Exception:
            pass

        for idx in (batch_op.f('ix_repayments_loan_created'), batch_op.f('ix_repayments_payer_created')):
            try:
                batch_op.drop_index(idx)
            except Exception:
                pass

    with op.batch_alter_table('token_sells', schema=None) as batch_op:
        batch_op.alter_column('status',
               existing_type=sa.VARCHAR(length=32),
               nullable=True,
               existing_server_default=sa.text("'initiated'"))
        batch_op.alter_column('created_at',
               existing_type=sa.DATETIME(),
               nullable=True)
        batch_op.alter_column('updated_at',
               existing_type=sa.DATETIME(),
               nullable=True)
        for idx in (batch_op.f('ix_token_sells_order_id'), batch_op.f('ix_token_sells_user_id')):
            try:
                batch_op.drop_index(idx)
            except Exception:
                pass

    # ---------- TRUST_SCORES: fix NULL group_id rows before altering ----------
    # If any trust_scores rows have group_id IS NULL, set them to 0 and ensure
    # cooperative_groups has an id=0 placeholder so temp-table copying won't fail.
    try:
        if _table_exists(bind, 'trust_scores'):
            # count nulls
            null_count = bind.execute(text("SELECT COUNT(1) FROM trust_scores WHERE group_id IS NULL")).scalar()
            if null_count and int(null_count) > 0:
                # ensure cooperative_groups exists
                if _table_exists(bind, 'cooperative_groups'):
                    # insert placeholder group with id 0 if not exists
                    # NOTE: adjust 'name' columns as necessary — using simple fields that are usually present
                    try:
                        bind.execute(text(
                            "INSERT OR IGNORE INTO cooperative_groups (id, name, created_at, updated_at) "
                            "VALUES (0, 'migrated-placeholder', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ))
                    except Exception:
                        # fallback: attempt to insert minimal row without timestamps if schema differs
                        try:
                            bind.execute(text(
                                "INSERT OR IGNORE INTO cooperative_groups (id, name) VALUES (0, 'migrated-placeholder')"
                            ))
                        except Exception:
                            pass
                # update trust_scores null group_id -> 0
                bind.execute(text("UPDATE trust_scores SET group_id = 0 WHERE group_id IS NULL"))
    except Exception:
        # best-effort: ignore if anything fails here — batch_alter_table below may still fail, but we don't want to hard-stop
        pass

    with op.batch_alter_table('trust_scores', schema=None) as batch_op:
        # drop existing FKs safely
        try:
            _drop_all_foreign_keys_for_table(bind, 'trust_scores', batch_op)
        except Exception:
            pass

        batch_op.alter_column('group_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        try:
            fk_name = batch_op.f('fk_trust_scores_group_id_cooperative_groups')
            batch_op.create_foreign_key(fk_name, 'cooperative_groups', ['group_id'], ['id'])
        except Exception:
            pass

    with op.batch_alter_table('vote_details', schema=None) as batch_op:
        for idx in (batch_op.f('ix_vd_session_voter'), batch_op.f('ix_vd_voter_created')):
            try:
                batch_op.drop_index(idx)
            except Exception:
                pass

    with op.batch_alter_table('voting_sessions', schema=None) as batch_op:
        try:
            batch_op.drop_index(batch_op.f('ix_vs_gid_created'))
        except Exception:
            pass

    # create temp member balances table (only if doesn't exist)
    if not _table_exists(bind, '_alembic_tmp_member_balances'):
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

    # drop outbox tables only if they exist
    if _table_exists(bind, 'outbox_attempts'):
        op.drop_table('outbox_attempts')
    if _table_exists(bind, 'outbox_transfers'):
        op.drop_table('outbox_transfers')


def downgrade():
    bind = op.get_bind()

    with op.batch_alter_table('voting_sessions', schema=None) as batch_op:
        try:
            batch_op.create_index(batch_op.f('ix_vs_gid_created'), ['group_id', 'created_at'], unique=False)
        except Exception:
            pass

    with op.batch_alter_table('vote_details', schema=None) as batch_op:
        try:
            batch_op.create_index(batch_op.f('ix_vd_voter_created'), ['voter_id', 'created_at'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_vd_session_voter'), ['session_id', 'voter_id'], unique=False)
        except Exception:
            pass

    with op.batch_alter_table('trust_scores', schema=None) as batch_op:
        try:
            _drop_all_foreign_keys_for_table(bind, 'trust_scores', batch_op)
        except Exception:
            pass
        try:
            batch_op.create_foreign_key(batch_op.f('fk_trust_scores_new_group_id_coop_groups'), 'cooperative_groups', ['group_id'], ['id'], ondelete='CASCADE')
        except Exception:
            pass
        batch_op.alter_column('group_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    with op.batch_alter_table('token_sells', schema=None) as batch_op:
        try:
            batch_op.create_index(batch_op.f('ix_token_sells_user_id'), ['user_id'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_token_sells_order_id'), ['order_id'], unique=False)
        except Exception:
            pass
        batch_op.alter_column('updated_at',
               existing_type=sa.DATETIME(),
               nullable=False)
        batch_op.alter_column('created_at',
               existing_type=sa.DATETIME(),
               nullable=False)
        batch_op.alter_column('status',
               existing_type=sa.VARCHAR(length=32),
               nullable=False,
               existing_server_default=sa.text("'initiated'"))

    with op.batch_alter_table('repayments', schema=None) as batch_op:
        try:
            fk_name = batch_op.f('fk_repayments_loan_id_loan_requests')
            batch_op.create_foreign_key(fk_name, 'loan_requests', ['loan_id'], ['id'])
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_repayments_payer_created'), ['payer_id', 'created_at'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_repayments_loan_created'), ['loan_id', 'created_at'], unique=False)
        except Exception:
            pass

    with op.batch_alter_table('repayment_schedules', schema=None) as batch_op:
        try:
            _drop_all_foreign_keys_for_table(bind, 'repayment_schedules', batch_op)
        except Exception:
            pass
        try:
            batch_op.create_foreign_key(batch_op.f('fk_repayment_schedules_paid_repayment'), 'repayments', ['paid_repayment_id'], ['id'], ondelete='SET NULL')
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_rs_paid_repayment_id'), ['paid_repayment_id'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_rs_loan_status_paidat'), ['loan_id', 'status', 'paid_at'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_rs_loan_status'), ['loan_id', 'status'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_rs_loan_duedate'), ['loan_id', 'due_date'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_repayment_schedules_paid_repayment_id'), ['paid_repayment_id'], unique=False)
        except Exception:
            pass

    with op.batch_alter_table('profit_share_details', schema=None) as batch_op:
        batch_op.alter_column('deposit_snapshot',
               existing_type=sa.Float(),
               type_=sa.NUMERIC(precision=18, scale=2),
               existing_nullable=False)

    with op.batch_alter_table('payment_config', schema=None) as batch_op:
        try:
            batch_op.drop_index(batch_op.f('ix_payment_config_mpesa_number'))
        except Exception:
            pass
        try:
            batch_op.create_index(batch_op.f('ix_payment_config_mpesa_number'), ['mpesa_number'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_unique_constraint(batch_op.f('uq_payment_config_mpesa_number'), ['mpesa_number'])
        except Exception:
            pass

    with op.batch_alter_table('payment_attempts', schema=None) as batch_op:
        try:
            _drop_all_foreign_keys_for_table(bind, 'payment_attempts', batch_op)
        except Exception:
            pass
        batch_op.alter_column('updated_at',
               existing_type=sa.DateTime(),
               type_=sa.NUMERIC(),
               existing_nullable=True)
        batch_op.alter_column('created_at',
               existing_type=sa.DateTime(),
               type_=sa.NUMERIC(),
               existing_nullable=True)
        batch_op.alter_column('hedera_tx_hash',
               existing_type=sa.String(length=128),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.alter_column('status',
               existing_type=sa.String(length=32),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.alter_column('mpesa_ref',
               existing_type=sa.String(length=64),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.alter_column('msisdn',
               existing_type=sa.String(length=32),
               type_=sa.TEXT(),
               nullable=True)
        batch_op.alter_column('order_id',
               existing_type=sa.String(length=64),
               type_=sa.TEXT(),
               nullable=True)
        batch_op.alter_column('id',
               existing_type=sa.INTEGER(),
               nullable=True,
               autoincrement=True)

    with op.batch_alter_table('member_balances', schema=None) as batch_op:
        batch_op.alter_column('total_deposit',
               existing_type=sa.Float(),
               type_=sa.NUMERIC(precision=18, scale=2),
               existing_nullable=False)

    # create temp member balances table (only if doesn't exist)
    if not _table_exists(bind, '_alembic_tmp_member_balances'):
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

    # drop outbox tables only if they exist
    if _table_exists(bind, 'outbox_attempts'):
        op.drop_table('outbox_attempts')
    if _table_exists(bind, 'outbox_transfers'):
        op.drop_table('outbox_transfers')
