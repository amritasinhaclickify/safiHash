"""add group_id to TrustScore for per-group tracking (sqlite-safe)

Revision ID: 9850a18ded8b
Revises: c7c5ff39e0a3
Create Date: 2025-10-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9850a18ded8b'
down_revision = 'c7c5ff39e0a3'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1) Create new table trust_scores_new with group_id and desired constraints
    op.create_table(
        'trust_scores_new',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_trust_scores_new_user_id_users'),
        sa.ForeignKeyConstraint(['group_id'], ['cooperative_groups.id'], name='fk_trust_scores_new_group_id_coop_groups', ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'group_id', name='uq_user_group_trustscore')
    )

    # 2) copy existing data (group_id will be NULL for existing rows)
    #    explicitly list columns to avoid surprises
    conn.execute(
        sa.text(
            "INSERT INTO trust_scores_new (id, user_id, score, updated_at, group_id) "
            "SELECT id, user_id, score, updated_at, NULL FROM trust_scores"
        )
    )

    # 3) drop old table then rename new to original name
    op.drop_table('trust_scores')
    op.rename_table('trust_scores_new', 'trust_scores')

    # 4) create indexes (SQLite will have them as separate objects)
    op.create_index('ix_trust_scores_user_id', 'trust_scores', ['user_id'], unique=False)
    op.create_index('ix_trust_scores_group_id', 'trust_scores', ['group_id'], unique=False)


def downgrade():
    conn = op.get_bind()

    # 1) recreate original trust_scores_old without group_id and with unique constraint on user_id
    op.create_table(
        'trust_scores_old',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=True, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_trust_scores_old_user_id_users'),
        sa.UniqueConstraint('user_id', name='uq_trust_scores_user_id_old')
    )

    # 2) copy back data - drop group_id (lost on downgrade)
    conn.execute(
        sa.text(
            "INSERT INTO trust_scores_old (id, user_id, score, updated_at) "
            "SELECT id, user_id, score, updated_at FROM trust_scores"
        )
    )

    # 3) drop current table and rename
    op.drop_index('ix_trust_scores_group_id', table_name='trust_scores')
    op.drop_index('ix_trust_scores_user_id', table_name='trust_scores')
    op.drop_table('trust_scores')
    op.rename_table('trust_scores_old', 'trust_scores')

    # 4) recreate the single-column index for user_id (if you want it)
    op.create_index('ix_trust_scores_user_id', 'trust_scores', ['user_id'], unique=False)
