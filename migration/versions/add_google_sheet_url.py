"""add_google_sheet_url

Revision ID: f7g8h9i0j1k2
Revises: a1b2c3d4e5f6
Create Date: 2026-01-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7g8h9i0j1k2'
down_revision: Union[str, Sequence[str], None] = '0af1710c7976'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем поле google_sheet_url в faculty
    op.add_column('faculty', sa.Column('google_sheet_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем поле из faculty
    op.drop_column('faculty', 'google_sheet_url')
