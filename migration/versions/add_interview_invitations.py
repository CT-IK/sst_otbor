"""add interview invitations and update interview model

Revision ID: fdc5759862c0
Revises: 43c91b2c4666
Create Date: 2026-02-01 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fdc5759862c0'
down_revision: Union[str, Sequence[str], None] = '43c91b2c4666'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем поля в interviews
    op.add_column('interviews', sa.Column('interview_time_slot_id', sa.Integer(), nullable=True))
    op.add_column('interviews', sa.Column('reschedule_count', sa.Integer(), nullable=False, server_default='0'))
    op.create_foreign_key('fk_interviews_interview_time_slot', 'interviews', 'interview_time_slots', ['interview_time_slot_id'], ['id'], ondelete='SET NULL')
    
    # Создаём таблицу interview_invitations
    op.create_table(
        'interview_invitations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sent_by'], ['administrators.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'faculty_id', name='uq_user_faculty_invitation')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('interview_invitations')
    op.drop_constraint('fk_interviews_interview_time_slot', 'interviews', type_='foreignkey')
    op.drop_column('interviews', 'reschedule_count')
    op.drop_column('interviews', 'interview_time_slot_id')
