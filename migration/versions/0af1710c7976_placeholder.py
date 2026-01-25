"""placeholder for missing migration

Revision ID: 0af1710c7976
Revises: a1b2c3d4e5f6
Create Date: 2026-01-25 16:00:00.000000

Эта миграция была применена ранее, но файл был удален.
Создана заглушка для восстановления цепочки миграций.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0af1710c7976'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Заглушка - миграция уже была применена ранее
    pass


def downgrade() -> None:
    """Downgrade schema."""
    # Заглушка - миграция уже была применена ранее
    pass
