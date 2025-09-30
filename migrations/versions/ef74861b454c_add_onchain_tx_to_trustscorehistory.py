"""add onchain_tx to TrustScoreHistory

Revision ID: ef74861b454c
Revises: 0442861af74e
Create Date: 2025-09-08 20:19:45.622758

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ef74861b454c'
down_revision = '0442861af74e'
branch_labels = None
depends_on = None


def upgrade():
    # Add new column onchain_tx to trust_score_history
    with op.batch_alter_table('trust_score_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('onchain_tx', sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f('ix_trust_score_history_onchain_tx'), ['onchain_tx'], unique=False)


def downgrade():
    # Remove column onchain_tx from trust_score_history
    with op.batch_alter_table('trust_score_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trust_score_history_onchain_tx'))
        batch_op.drop_column('onchain_tx')
