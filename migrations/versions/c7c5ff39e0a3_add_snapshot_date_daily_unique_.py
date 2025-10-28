# migrations/versions/c7c5ff39e0a3_add_snapshot_date_daily_unique_.py
revision = "c7c5ff39e0a3"
down_revision = "3bffc224e285"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("trust_score_history")]

    # 1) add column if missing
    if "snapshot_date" not in cols:
        with op.batch_alter_table("trust_score_history", recreate="auto") as b:
            b.add_column(sa.Column("snapshot_date", sa.Date(), nullable=True))

    # 2) backfill (date(created_at)) + set NOT NULL
    op.execute("UPDATE trust_score_history SET snapshot_date = DATE(created_at) WHERE snapshot_date IS NULL;")
    with op.batch_alter_table("trust_score_history", recreate="auto") as b:
        b.alter_column("snapshot_date", existing_type=sa.Date(), nullable=False)

    # 3) de-duplicate rows per (user,group,reason,snapshot_date) keeping latest id
    op.execute("""
        DELETE FROM trust_score_history
        WHERE id NOT IN (
          SELECT MAX(id) FROM trust_score_history
          GROUP BY user_id, group_id, reason, snapshot_date
        );
    """)

    # 4) create index if missing
    idx_names = {i["name"] for i in insp.get_indexes("trust_score_history")}
    if "ix_trust_score_history_snapshot_date" not in idx_names:
        op.create_index("ix_trust_score_history_snapshot_date", "trust_score_history", ["snapshot_date"])

    # 5) unique constraint if missing
    uq_names = {c["name"] for c in insp.get_unique_constraints("trust_score_history")}
    if "uq_trustscore_daily" not in uq_names:
        with op.batch_alter_table("trust_score_history", recreate="auto") as b:
            b.create_unique_constraint(
                "uq_trustscore_daily",
                ["user_id", "group_id", "reason", "snapshot_date"]
            )

def downgrade():
    with op.batch_alter_table("trust_score_history", recreate="auto") as b:
        b.drop_constraint("uq_trustscore_daily", type_="unique")
    op.drop_index("ix_trust_score_history_snapshot_date", table_name="trust_score_history")
    with op.batch_alter_table("trust_score_history", recreate="auto") as b:
        b.drop_column("snapshot_date")
