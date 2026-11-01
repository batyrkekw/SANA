"""Administrator testing with zero-cost, auditable generations.

Revision ID: a8c4e102b937
Revises: 4ea4d575eed9
"""

import sqlalchemy as sa
from alembic import op

revision = "a8c4e102b937"
down_revision = "4ea4d575eed9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "profiles", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.drop_constraint("generation_jobs_cost_check", "generation_jobs", type_="check")
    op.create_check_constraint(
        "ck_generation_jobs_cost_nonnegative", "generation_jobs", "cost >= 0"
    )


def downgrade():
    # Refuse a lossy downgrade once zero-cost audit records exist.
    op.create_check_constraint("generation_jobs_cost_check", "generation_jobs", "cost > 0")
    op.drop_constraint("ck_generation_jobs_cost_nonnegative", "generation_jobs", type_="check")
    op.drop_column("profiles", "is_admin")
