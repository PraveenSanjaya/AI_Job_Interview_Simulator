"""add job descriptions, analyses and matches

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04 18:15:52.251175

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('job_descriptions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('company', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('source_url', sa.String(length=2000), nullable=True),
    sa.Column('status', sa.Enum('saved', 'parsed', 'failed', name='jobstatus', native_enum=False, length=20), nullable=False),
    sa.Column('description_sha256', sa.String(length=64), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_job_descriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_descriptions'))
    )
    op.create_index('ix_job_descriptions_user_id_created_at', 'job_descriptions', ['user_id', 'created_at'], unique=False)

    op.create_table('job_analyses',
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('parser', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('consent_external_ai', sa.Boolean(), nullable=False),
    sa.Column('input_truncated', sa.Boolean(), nullable=False),
    sa.Column('description_sha256', sa.String(length=64), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['job_descriptions.id'], name=op.f('fk_job_analyses_job_id_job_descriptions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_job_analyses_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_analyses')),
    sa.UniqueConstraint('job_id', name=op.f('uq_job_analyses_job_id'))
    )
    op.create_index(op.f('ix_job_analyses_user_id'), 'job_analyses', ['user_id'], unique=False)

    op.create_table('job_matches',
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('overall_score', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.String(length=20), nullable=False),
    sa.Column('scoring_config', sa.JSON(), nullable=False),
    sa.Column('evidence_used', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('ai_provider', sa.String(length=50), nullable=True),
    sa.Column('ai_model', sa.String(length=100), nullable=True),
    sa.Column('consent_external_ai', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['job_descriptions.id'], name=op.f('fk_job_matches_job_id_job_descriptions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_job_matches_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_matches'))
    )
    op.create_index('ix_job_matches_job_id_created_at', 'job_matches', ['job_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_job_matches_user_id'), 'job_matches', ['user_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_job_matches_user_id'), table_name='job_matches')
    op.drop_index('ix_job_matches_job_id_created_at', table_name='job_matches')

    op.drop_table('job_matches')
    op.drop_index(op.f('ix_job_analyses_user_id'), table_name='job_analyses')

    op.drop_table('job_analyses')
    op.drop_index('ix_job_descriptions_user_id_created_at', table_name='job_descriptions')

    op.drop_table('job_descriptions')
