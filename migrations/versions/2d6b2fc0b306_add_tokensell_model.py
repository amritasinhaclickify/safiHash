"""add TokenSell model

Revision ID: 2d6b2fc0b306
Revises: 9850a18ded8b
Create Date: 2025-10-10 18:47:35.868446
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '2d6b2fc0b306'
down_revision = '9850a18ded8b'
branch_labels = None
depends_on = None


def upgrade():
    # --- Create token_sells table only (SQLite-safe) ---
    op.create_table(
        'token_sells',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('bhc_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('kes_value', sa.Numeric(12, 2), nullable=False),
        sa.Column('rate', sa.Numeric(12, 2), nullable=False),
        sa.Column('order_id', sa.String(64), sa.ForeignKey('payment_orders.order_id'), nullable=True, index=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='initiated'),
        sa.Column('hedera_tx_hash', sa.String(128), nullable=True),
        sa.Column('payout_ref', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=datetime.utcnow),
        sa.Column('updated_at', sa.DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow),
    )
    # --- end create ---


def downgrade():
    op.drop_table('token_sells')
