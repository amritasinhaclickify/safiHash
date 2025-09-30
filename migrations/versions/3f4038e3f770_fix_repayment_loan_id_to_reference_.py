"""Fix Repayment.loan_id to reference loans.id instead of loan_requests.id

Revision ID: 3f4038e3f770
Revises: 4c86cc64cac6
Create Date: 2025-09-05 12:22:12.722608

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f4038e3f770'
down_revision = '4c86cc64cac6'
branch_labels = None
depends_on = None


def upgrade():
    # Use batch_alter_table so Alembic will recreate the table for SQLite safely
    with op.batch_alter_table('repayments', schema=None) as batch_op:
        # create indexes (autogen reported them added)
        # Use explicit names so we can drop them later reliably
        batch_op.create_index('ix_repayments_loan_id', ['loan_id'], unique=False)
        batch_op.create_index('ix_repayments_payer_id', ['payer_id'], unique=False)

        # add a named FK from repayments.loan_id -> loans.id
        # Naming the constraint avoids "Constraint must have a name" issues on SQLite
        batch_op.create_foreign_key(
            'fk_repayments_loan_id_loans',    # explicit name
            'loans',                         # referred table
            ['loan_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('repayments', schema=None) as batch_op:
        # drop the FK we created
        batch_op.drop_constraint('fk_repayments_loan_id_loans', type_='foreignkey')
        # drop the indexes
        batch_op.drop_index('ix_repayments_loan_id')
        batch_op.drop_index('ix_repayments_payer_id')
