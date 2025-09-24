"""add completed_tasks table

Revision ID: c9d8e7f6b5a4
Revises: d0f68be88eec
Create Date: 2025-09-18 09:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9d8e7f6b5a4'
down_revision = 'd0f68be88eec'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'completed_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('original_task_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('observations', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(20), nullable=True),
        sa.Column('assignee', sa.String(100), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('data_criacao', sa.DateTime(), nullable=True),
        sa.Column('data_conclusao', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=False),
        sa.Column('attachment_path', sa.String(255), nullable=True),
    )

def downgrade():
    op.drop_table('completed_tasks')
