"""add interview sessions, questions, answers, evaluations and reports

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04 19:21:28.975289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('interview_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('job_snapshot', sa.JSON(), nullable=True),
    sa.Column('interview_types', sa.JSON(), nullable=False),
    sa.Column('difficulty', sa.Enum('beginner', 'intermediate', 'advanced', name='sessiondifficulty', native_enum=False, length=20), nullable=False),
    sa.Column('question_count', sa.Integer(), nullable=False),
    sa.Column('max_followups', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('created', 'in_progress', 'completed', 'cancelled', 'interrupted', 'expired', name='interviewstatus', native_enum=False, length=20), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=True),
    sa.Column('ai_status', sa.String(length=40), nullable=True),
    sa.Column('use_ai', sa.Boolean(), nullable=False),
    sa.Column('consent_external_ai', sa.Boolean(), nullable=False),
    sa.Column('ai_provider', sa.String(length=50), nullable=True),
    sa.Column('ai_model', sa.String(length=100), nullable=True),
    sa.Column('scoring_config', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('current_index', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['job_descriptions.id'], name=op.f('fk_interview_sessions_job_id_job_descriptions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interview_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_sessions'))
    )
    op.create_index('ix_interview_sessions_user_id_created_at', 'interview_sessions', ['user_id', 'created_at'], unique=False)

    op.create_table('interview_questions',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('main_index', sa.Integer(), nullable=False),
    sa.Column('followup_index', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('followup_kind', sa.String(length=20), nullable=True),
    sa.Column('skill_tags', sa.JSON(), nullable=False),
    sa.Column('expected_points', sa.JSON(), nullable=False),
    sa.Column('asked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_interview_questions_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interview_questions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_questions')),
    sa.UniqueConstraint('session_id', 'main_index', 'followup_index', name=op.f('uq_interview_questions_session_id'))
    )
    op.create_index('ix_interview_questions_session_id', 'interview_questions', ['session_id'], unique=False)

    op.create_table('interview_reports',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('overall_score', sa.Integer(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_interview_reports_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interview_reports_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_reports')),
    sa.UniqueConstraint('session_id', name=op.f('uq_interview_reports_session_id'))
    )
    op.create_index(op.f('ix_interview_reports_user_id'), 'interview_reports', ['user_id'], unique=False)

    op.create_table('interview_answers',
    sa.Column('question_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('skipped', sa.Boolean(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['interview_questions.id'], name=op.f('fk_interview_answers_question_id_interview_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_interview_answers_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interview_answers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_answers')),
    sa.UniqueConstraint('question_id', name=op.f('uq_interview_answers_question_id'))
    )
    op.create_index(op.f('ix_interview_answers_session_id'), 'interview_answers', ['session_id'], unique=False)

    op.create_table('interview_evaluations',
    sa.Column('answer_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('evaluated', 'unavailable', 'failed', 'not_evaluated', name='evaluationstatus', native_enum=False, length=20), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['answer_id'], ['interview_answers.id'], name=op.f('fk_interview_evaluations_answer_id_interview_answers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_interview_evaluations_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interview_evaluations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_evaluations')),
    sa.UniqueConstraint('answer_id', name=op.f('uq_interview_evaluations_answer_id'))
    )
    op.create_index(op.f('ix_interview_evaluations_session_id'), 'interview_evaluations', ['session_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_interview_evaluations_session_id'), table_name='interview_evaluations')

    op.drop_table('interview_evaluations')
    op.drop_index(op.f('ix_interview_answers_session_id'), table_name='interview_answers')

    op.drop_table('interview_answers')
    op.drop_index(op.f('ix_interview_reports_user_id'), table_name='interview_reports')

    op.drop_table('interview_reports')
    op.drop_index('ix_interview_questions_session_id', table_name='interview_questions')

    op.drop_table('interview_questions')
    op.drop_index('ix_interview_sessions_user_id_created_at', table_name='interview_sessions')

    op.drop_table('interview_sessions')
