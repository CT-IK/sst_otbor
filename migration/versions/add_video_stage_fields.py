"""add_video_stage_fields

Revision ID: a1b2c3d4e5f6
Revises: dffec56257a2
Create Date: 2026-01-15 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'dffec56257a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем поле added_by в administrators
    op.add_column('administrators', sa.Column('added_by', sa.BigInteger(), nullable=True))
    
    # Добавляем поля для этапа видео в faculty
    op.add_column('faculty', sa.Column('video_chat_id', sa.BigInteger(), nullable=True))
    op.add_column('faculty', sa.Column('video_submission_open', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем поля из faculty
    op.drop_column('faculty', 'video_submission_open')
    op.drop_column('faculty', 'video_chat_id')
    
    # Удаляем поле из administrators
    op.drop_column('administrators', 'added_by')
