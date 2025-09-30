"""add trust score weights to policy_rules"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3bffc224e285'
down_revision = '572c4ef95d32'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('policy_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('w_deposit_consistency', sa.Numeric(5,2), nullable=False, server_default="15"))
        batch_op.add_column(sa.Column('w_repayment_timeliness', sa.Numeric(5,2), nullable=False, server_default="20"))
        batch_op.add_column(sa.Column('w_ontime_repayments', sa.Numeric(5,2), nullable=False, server_default="15"))
        batch_op.add_column(sa.Column('w_voting_participation', sa.Numeric(5,2), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column('w_loan_request_freq', sa.Numeric(5,2), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column('w_loan_approval_rate', sa.Numeric(5,2), nullable=False, server_default="10"))
        batch_op.add_column(sa.Column('w_disbursal_timeliness', sa.Numeric(5,2), nullable=False, server_default="10"))
        batch_op.add_column(sa.Column('w_self_repayment', sa.Numeric(5,2), nullable=False, server_default="10"))
        batch_op.add_column(sa.Column('w_thirdparty_flag', sa.Numeric(5,2), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column('w_profit_contribution', sa.Numeric(5,2), nullable=False, server_default="5"))


def downgrade():
    with op.batch_alter_table('policy_rules', schema=None) as batch_op:
        batch_op.drop_column('w_profit_contribution')
        batch_op.drop_column('w_thirdparty_flag')
        batch_op.drop_column('w_self_repayment')
        batch_op.drop_column('w_disbursal_timeliness')
        batch_op.drop_column('w_loan_approval_rate')
        batch_op.drop_column('w_loan_request_freq')
        batch_op.drop_column('w_voting_participation')
        batch_op.drop_column('w_ontime_repayments')
        batch_op.drop_column('w_repayment_timeliness')
        batch_op.drop_column('w_deposit_consistency')
