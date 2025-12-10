"""add cover field to Users

Revision ID: add_cover_field
Revises: add_profile_fields
Create Date: 2025-01-10
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cover_field'
down_revision = 'add_profile_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('Users', sa.Column('cover_path', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('Users', 'cover_path')
