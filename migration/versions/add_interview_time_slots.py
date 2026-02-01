"""add interview_time_slots table

Revision ID: 43c91b2c4666
Revises: 75983d88323e
Create Date: 2026-02-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43c91b2c4666'
down_revision: Union[str, Sequence[str], None] = '75983d88323e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Создаём таблицу interview_time_slots
    op.create_table(
        'interview_time_slots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('time', sa.Time(), nullable=False),
        sa.Column('max_participants', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('faculty_id', 'date', 'time', name='uq_faculty_date_time')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('interview_time_slots')
