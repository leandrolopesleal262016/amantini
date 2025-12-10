"""add profile fields to Users

Revision ID: add_profile_fields
Revises: c9d8e7f6b5a4
Create Date: 2025-01-10
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_profile_fields'
down_revision = 'c9d8e7f6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('Users', sa.Column('first_name', sa.String(length=64), nullable=True))
    op.add_column('Users', sa.Column('last_name', sa.String(length=64), nullable=True))
    op.add_column('Users', sa.Column('phone', sa.String(length=32), nullable=True))
    op.add_column('Users', sa.Column('address', sa.String(length=255), nullable=True))
    op.add_column('Users', sa.Column('city', sa.String(length=64), nullable=True))
    op.add_column('Users', sa.Column('country', sa.String(length=64), nullable=True))
    op.add_column('Users', sa.Column('postal_code', sa.String(length=20), nullable=True))
    op.add_column('Users', sa.Column('bio', sa.Text(), nullable=True))
    op.add_column('Users', sa.Column('avatar_path', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('Users', 'avatar_path')
    op.drop_column('Users', 'bio')
    op.drop_column('Users', 'postal_code')
    op.drop_column('Users', 'country')
    op.drop_column('Users', 'city')
    op.drop_column('Users', 'address')
    op.drop_column('Users', 'phone')
    op.drop_column('Users', 'last_name')
    op.drop_column('Users', 'first_name')
