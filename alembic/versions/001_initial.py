"""initial migration

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("company_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("is_verified", sa.Boolean, default=False),
        sa.Column("tier", sa.String(20), default="free", nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), unique=True),
        sa.Column("current_period_end", sa.DateTime),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_stripe_customer", "users", ["stripe_customer_id"], unique=True)

    # API Keys table
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("last_used_at", sa.DateTime),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
    )
    op.create_index("ix_api_keys_user", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)

    # Documents table
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL")),
        sa.Column("filename", sa.String(500)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("file_size", sa.BigInteger),
        sa.Column("storage_path", sa.String(500)),
        sa.Column("document_type", sa.String(50), default="unknown", nullable=False),
        sa.Column("status", sa.String(20), default="pending", nullable=False),
        sa.Column("parsed_data", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("processing_time_ms", sa.Integer),
        sa.Column("webhook_url", sa.String(500)),
        sa.Column("webhook_status", sa.String(50)),
        sa.Column("webhook_attempts", sa.Integer, default=0),
        sa.Column("webhook_last_attempt", sa.DateTime),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("ix_documents_user", "documents", ["user_id"])
    op.create_index("ix_documents_created", "documents", ["created_at"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_type", "documents", ["document_type"])

    # Usage Logs table
    op.create_table(
        "usage_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL")),
        sa.Column("endpoint", sa.String(100), nullable=False),
        sa.Column("document_type", sa.String(50)),
        sa.Column("status_code", sa.Integer),
        sa.Column("response_time_ms", sa.Integer),
        sa.Column("request_size_bytes", sa.BigInteger),
        sa.Column("response_size_bytes", sa.BigInteger),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.Text),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
    )
    op.create_index("ix_usage_logs_user", "usage_logs", ["user_id"])
    op.create_index("ix_usage_logs_created", "usage_logs", ["created_at"])
    op.create_index("ix_usage_logs_endpoint", "usage_logs", ["endpoint"])

    # Subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), unique=True),
        sa.Column("stripe_price_id", sa.String(255)),
        sa.Column("stripe_current_period_start", sa.DateTime),
        sa.Column("stripe_current_period_end", sa.DateTime),
        sa.Column("stripe_cancel_at_period_end", sa.Boolean, default=False),
        sa.Column("status", sa.String(50)),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_subscriptions_user", "subscriptions", ["user_id"], unique=True)
    op.create_index("ix_subscriptions_stripe", "subscriptions", ["stripe_subscription_id"], unique=True)


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("usage_logs")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.drop_table("users")
