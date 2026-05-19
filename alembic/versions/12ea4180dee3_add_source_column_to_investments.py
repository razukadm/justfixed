"""add source column to investments

Revision ID: 12ea4180dee3
Revises: 8010f6133718
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12ea4180dee3'
down_revision: Union[str, Sequence[str], None] = '8010f6133718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('investments',
        sa.Column('source', sa.String(), nullable=False, server_default='xp_import')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('investments', 'source')
