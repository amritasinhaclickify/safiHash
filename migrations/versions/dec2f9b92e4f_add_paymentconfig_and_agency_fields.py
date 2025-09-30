"""Add PaymentConfig and agency fields

Revision ID: dec2f9b92e4f
Revises: a08de9fc5264
Create Date: 2025-09-24 14:26:51.261589

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dec2f9b92e4f'
down_revision = 'a08de9fc5264'
branch_labels = None
depends_on = None


def upgrade():
    # create new table payment_config
    op.create_table(
        'payment_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('mpesa_number', sa.String(length=32), nullable=True),
        sa.Column('hedera_account_id', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    # index on mpesa_number
    with op.batch_alter_table('payment_config', schema=None) as batch_op:
        batch_op.create_index('ix_payment_config_mpesa_number', ['mpesa_number'], unique=False)

    # payment_attempts: add agency_number column + index
    with op.batch_alter_table('payment_attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agency_number', sa.String(length=32), nullable=True))
        batch_op.create_index('ix_payment_attempts_agency_number', ['agency_number'], unique=False)
        # msisdn index may already exist; create only if missing in your DB
        batch_op.create_index('ix_payment_attempts_msisdn', ['msisdn'], unique=False)

    # payment_orders: add agency fields + indexes + FKs (give explicit names)
    with op.batch_alter_table('payment_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agency_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('agency_number', sa.String(length=32), nullable=True))
        batch_op.create_index('ix_payment_orders_agency_id', ['agency_id'], unique=False)
        batch_op.create_index('ix_payment_orders_agency_number', ['agency_number'], unique=False)
        batch_op.create_index('ix_payment_orders_msisdn', ['msisdn'], unique=False)

        # create named foreign keys
        batch_op.create_foreign_key('fk_payment_orders_user_id_users', 'users', ['user_id'], ['id'])
        batch_op.create_foreign_key('fk_payment_orders_agency_id_payment_config', 'payment_config', ['agency_id'], ['id'])


def downgrade():
    # reverse changes
    with op.batch_alter_table('payment_orders', schema=None) as batch_op:
        # drop named FKs and indexes and columns
        batch_op.drop_constraint('fk_payment_orders_agency_id_payment_config', type_='foreignkey')
        # the user_fk may already exist; attempt to drop if present
        try:
            batch_op.drop_constraint('fk_payment_orders_user_id_users', type_='foreignkey')
        except Exception:
            pass
        batch_op.drop_index('ix_payment_orders_msisdn')
        batch_op.drop_index('ix_payment_orders_agency_number')
        batch_op.drop_index('ix_payment_orders_agency_id')
        batch_op.drop_column('agency_number')
        batch_op.drop_column('agency_id')

    with op.batch_alter_table('payment_attempts', schema=None) as batch_op:
        batch_op.drop_index('ix_payment_attempts_msisdn')
        batch_op.drop_index('ix_payment_attempts_agency_number')
        batch_op.drop_column('agency_number')

    with op.batch_alter_table('payment_config', schema=None) as batch_op:
        batch_op.drop_index('ix_payment_config_mpesa_number')

    op.drop_table('payment_config')
