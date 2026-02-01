"""add interviewers table

Revision ID: bdb260946a10
Revises: add_interview_interviewers
Create Date: 2026-01-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bdb260946a10'
down_revision: Union[str, None] = '96afbe4c51fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаём таблицу interviewers
    op.create_table(
        'interviewers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('username', sa.String(length=50), nullable=True),
        sa.Column('full_name', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('added_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['added_by'], ['administrators.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', 'faculty_id', name='uq_interviewer_telegram_faculty')
    )
    
    # Мигрируем данные из administrators в interviewers (только reviewer и head_admin)
    # Сначала создаём временную колонку для хранения старого interviewer_id
    op.add_column('interviewer_schedule', sa.Column('old_interviewer_id', sa.Integer(), nullable=True))
    op.add_column('interview_interviewers', sa.Column('old_interviewer_id', sa.Integer(), nullable=True))
    
    # Копируем данные из administrators в interviewers
    # Используем DISTINCT ON чтобы избежать дубликатов для одного (telegram_id, faculty_id)
    op.execute("""
        INSERT INTO interviewers (telegram_id, faculty_id, name, username, full_name, is_active, added_by, created_at, updated_at)
        SELECT DISTINCT ON (telegram_id, faculty_id)
            telegram_id, faculty_id, name, username, full_name, is_active, NULL, created_at, NOW()
        FROM administrators
        WHERE is_active = true AND (role = 'reviewer' OR role = 'head_admin')
        ORDER BY telegram_id, faculty_id, id
    """)
    
    # Обновляем interviewer_schedule: связываем старые interviewer_id с новыми
    op.execute("""
        UPDATE interviewer_schedule
        SET old_interviewer_id = interviewer_id
    """)
    
    # Обновляем связи в interviewer_schedule
    # Используем подзапрос для выбора одного interviewer_id для каждого (telegram_id, faculty_id)
    op.execute("""
        UPDATE interviewer_schedule isch
        SET interviewer_id = (
            SELECT i.id
            FROM interviewers i
            JOIN administrators a ON a.telegram_id = i.telegram_id AND a.faculty_id = i.faculty_id
            WHERE a.id = isch.old_interviewer_id
            LIMIT 1
        )
        WHERE isch.old_interviewer_id IS NOT NULL
    """)
    
    # Удаляем дубликаты после обновления (оставляем только первую запись для каждой комбинации)
    # Это нужно, чтобы избежать нарушения уникального ограничения uq_interviewer_date_time
    op.execute("""
        DELETE FROM interviewer_schedule isch1
        WHERE isch1.id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY interviewer_id, date, time_slot 
                    ORDER BY id
                ) as rn
                FROM interviewer_schedule
                WHERE interviewer_id IS NOT NULL
            ) t
            WHERE t.rn > 1
        )
    """)
    
    # Обновляем interview_interviewers аналогично
    op.execute("""
        UPDATE interview_interviewers ii
        SET old_interviewer_id = interviewer_id
    """)
    
    op.execute("""
        UPDATE interview_interviewers ii
        SET interviewer_id = i.id
        FROM interviewers i
        JOIN administrators a ON a.telegram_id = i.telegram_id AND a.faculty_id = i.faculty_id
        WHERE ii.old_interviewer_id = a.id
    """)
    
    # Удаляем временные колонки
    op.drop_column('interviewer_schedule', 'old_interviewer_id')
    op.drop_column('interview_interviewers', 'old_interviewer_id')
    
    # Удаляем старые foreign key constraints
    op.drop_constraint('interviewer_schedule_interviewer_id_fkey', 'interviewer_schedule', type_='foreignkey')
    op.drop_constraint('interview_interviewers_interviewer_id_fkey', 'interview_interviewers', type_='foreignkey')
    
    # Создаём новые foreign key constraints на interviewers
    op.create_foreign_key(
        'fk_interviewer_schedule_interviewer',
        'interviewer_schedule',
        'interviewers',
        ['interviewer_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_interview_interviewers_interviewer',
        'interview_interviewers',
        'interviewers',
        ['interviewer_id'],
        ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    # Удаляем новые foreign key constraints
    op.drop_constraint('fk_interview_interviewers_interviewer', 'interview_interviewers', type_='foreignkey')
    op.drop_constraint('fk_interviewer_schedule_interviewer', 'interviewer_schedule', type_='foreignkey')
    
    # Восстанавливаем старые foreign key constraints
    op.create_foreign_key(
        'interview_interviewers_interviewer_id_fkey',
        'interview_interviewers',
        'administrators',
        ['interviewer_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'interviewer_schedule_interviewer_id_fkey',
        'interviewer_schedule',
        'administrators',
        ['interviewer_id'],
        ['id'],
        ondelete='CASCADE'
    )
    
    # Мигрируем данные обратно (если нужно)
    # Удаляем таблицу interviewers
    op.drop_table('interviewers')
