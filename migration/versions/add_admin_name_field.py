"""add admin name field

Revision ID: 75983d88323e
Revises: 2e519169d51f
Create Date: 2026-02-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75983d88323e'
down_revision: Union[str, Sequence[str], None] = '2e519169d51f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем поле name в administrators
    op.add_column('administrators', sa.Column('name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('administrators', 'name')
