from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0bf163bfa91e'
down_revision = 'a50798ce9d6f'
branch_labels = None
depends_on = None


def upgrade():
    # deposits
    op.create_index('ix_deposits_gid_created', 'deposits', ['group_id','created_at'], unique=False)
    op.create_index('ix_deposits_gid_uid_created', 'deposits', ['group_id','user_id','created_at'], unique=False)

    # repayments
    op.create_index('ix_repayments_loan_created', 'repayments', ['loan_id','created_at'], unique=False)
    op.create_index('ix_repayments_payer_created', 'repayments', ['payer_id','created_at'], unique=False)

    # repayment_schedules
    op.create_index('ix_rs_loan_status', 'repayment_schedules', ['loan_id','status'], unique=False)
    op.create_index('ix_rs_loan_status_paidat', 'repayment_schedules', ['loan_id','status','paid_at'], unique=False)
    op.create_index('ix_rs_loan_duedate', 'repayment_schedules', ['loan_id','due_date'], unique=False)
    op.create_index('ix_rs_paid_repayment_id', 'repayment_schedules', ['paid_repayment_id'], unique=False)

    # loans
    op.create_index('ix_loans_gid_uid', 'loans', ['group_id','user_id'], unique=False)
    op.create_index('ix_loans_gid_status', 'loans', ['group_id','status'], unique=False)
    op.create_index('ix_loans_gid_uid_disb', 'loans', ['group_id','user_id','disbursed_at'], unique=False)
    op.create_index('ix_loans_gid_created', 'loans', ['group_id','created_at'], unique=False)

    # loan_requests
    op.create_index('ix_lr_gid_uid_created', 'loan_requests', ['group_id','user_id','created_at'], unique=False)
    op.create_index('ix_lr_gid_status', 'loan_requests', ['group_id','status'], unique=False)

    # voting_sessions & vote_details
    op.create_index('ix_vs_gid_created', 'voting_sessions', ['group_id','created_at'], unique=False)
    op.create_index('ix_vd_session_voter', 'vote_details', ['session_id','voter_id'], unique=False)
    op.create_index('ix_vd_voter_created', 'vote_details', ['voter_id','created_at'], unique=False)

    # payment_audit
    op.create_index('ix_pa_gid_borrower_status', 'payment_audit', ['group_id','borrower_id','status'], unique=False)
    op.create_index('ix_pa_gid_status_created', 'payment_audit', ['group_id','status','created_at'], unique=False)

    # group_membership / member_balance
    op.create_index('ix_gm_gid_uid', 'group_membership', ['group_id','user_id'], unique=False)
    op.create_index('ix_mb_gid_uid', 'member_balance', ['group_id','user_id'], unique=False)

    # transaction_ledger
    op.create_index('ix_tl_gid_type_created', 'transaction_ledger', ['group_id','ref_type','created_at'], unique=False)
    op.create_index('ix_tl_gid_uid_created', 'transaction_ledger', ['group_id','user_id','created_at'], unique=False)

    # trust_score_history
    op.create_index('ix_tsh_gid_uid_created', 'trust_score_history', ['group_id','user_id','created_at'], unique=False)


def downgrade():
    op.drop_index('ix_tsh_gid_uid_created', table_name='trust_score_history')

    op.drop_index('ix_tl_gid_uid_created', table_name='transaction_ledger')
    op.drop_index('ix_tl_gid_type_created', table_name='transaction_ledger')

    op.drop_index('ix_mb_gid_uid', table_name='member_balance')
    op.drop_index('ix_gm_gid_uid', table_name='group_membership')

    op.drop_index('ix_pa_gid_status_created', table_name='payment_audit')
    op.drop_index('ix_pa_gid_borrower_status', table_name='payment_audit')

    op.drop_index('ix_vd_voter_created', table_name='vote_details')
    op.drop_index('ix_vd_session_voter', table_name='vote_details')
    op.drop_index('ix_vs_gid_created', table_name='voting_sessions')

    op.drop_index('ix_lr_gid_status', table_name='loan_requests')
    op.drop_index('ix_lr_gid_uid_created', table_name='loan_requests')

    op.drop_index('ix_loans_gid_created', table_name='loans')
    op.drop_index('ix_loans_gid_uid_disb', table_name='loans')
    op.drop_index('ix_loans_gid_status', table_name='loans')
    op.drop_index('ix_loans_gid_uid', table_name='loans')

    op.drop_index('ix_rs_paid_repayment_id', table_name='repayment_schedules')
    op.drop_index('ix_rs_loan_duedate', table_name='repayment_schedules')
    op.drop_index('ix_rs_loan_status_paidat', table_name='repayment_schedules')
    op.drop_index('ix_rs_loan_status', table_name='repayment_schedules')

    op.drop_index('ix_repayments_payer_created', table_name='repayments')
    op.drop_index('ix_repayments_loan_created', table_name='repayments')

    op.drop_index('ix_deposits_gid_uid_created', table_name='deposits')
    op.drop_index('ix_deposits_gid_created', table_name='deposits')
