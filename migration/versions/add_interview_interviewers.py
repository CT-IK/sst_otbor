"""add interview_interviewers table

Revision ID: 96afbe4c51fe
Revises: fdc5759862c0
Create Date: 2026-02-01 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96afbe4c51fe'
down_revision: Union[str, Sequence[str], None] = 'fdc5759862c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'interview_interviewers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('interview_id', sa.Integer(), nullable=False),
        sa.Column('interviewer_id', sa.Integer(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['interview_id'], ['interviews.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['interviewer_id'], ['administrators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['administrators.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('interview_id', 'interviewer_id', name='uq_interview_interviewer')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('interview_interviewers')
