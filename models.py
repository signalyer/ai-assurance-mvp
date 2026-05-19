"""Multi-tenant data models for enterprise platform."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, JSON, UUID, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import uuid

Base = declarative_base()


class Customer(Base):
    """Represents a customer/tenant."""
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    industry = Column(String(50), nullable=False)  # healthcare, financial_services
    deployment_type = Column(String(50))  # saas, on_prem, hybrid
    subscription_tier = Column(String(50), default="starter")  # starter, pro, enterprise

    # Compliance flags
    hipaa_enabled = Column(Boolean, default=False)
    soc2_enabled = Column(Boolean, default=False)
    gdpr_enabled = Column(Boolean, default=False)

    # Data residency
    data_residency = Column(String(50), default="us")  # us, eu, apac

    # Database schema name (e.g., customer_abc123)
    schema_name = Column(String(100), unique=True, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relationships
    users = relationship("User", back_populates="customer", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="customer", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="customer", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_customer_schema_name', 'schema_name'),
        Index('ix_customer_industry', 'industry'),
        Index('ix_customer_active', 'is_active'),
    )


class User(Base):
    """Represents a user within a customer account."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    name = Column(String(255))

    # Authentication
    auth_provider = Column(String(50))  # oauth, saml, api_key, service_account
    external_id = Column(String(255))  # ID from OAuth provider

    # Roles: owner, admin, analyst, api
    role = Column(String(50), default="analyst", nullable=False)

    # Security
    mfa_enabled = Column(Boolean, default=False)
    mfa_verified = Column(Boolean, default=False)
    password_hash = Column(String(255))  # For fallback auth

    # Status
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    customer = relationship("Customer", back_populates="users")

    __table_args__ = (
        Index('ix_user_customer_email', 'customer_id', 'email'),
        Index('ix_user_active', 'is_active'),
    )


class APIKey(Base):
    """API key for programmatic access."""
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)

    # Key management
    key_hash = Column(String(255), nullable=False, unique=True)  # bcrypt hash
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Permissions
    scope = Column(String(255))  # read, write, admin

    # Lifecycle
    is_active = Column(Boolean, default=True)
    last_used = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    rotated_at = Column(DateTime)

    # Relationships
    customer = relationship("Customer", back_populates="api_keys")

    __table_args__ = (
        Index('ix_apikey_customer', 'customer_id'),
        Index('ix_apikey_active', 'is_active'),
    )


class AuditLog(Base):
    """Immutable audit trail for compliance."""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Action details
    action = Column(String(50), nullable=False)  # create, read, update, delete, access_denied
    resource_type = Column(String(50), nullable=False)  # Domain, Run, Evaluation, User
    resource_id = Column(UUID(as_uuid=True))

    # Change tracking
    before_state = Column(JSON)  # Previous values
    after_state = Column(JSON)   # New values
    change_details = Column(JSON)  # Detailed diff

    # Request context
    ip_address = Column(String(45))  # IPv4/IPv6
    user_agent = Column(Text)

    # Immutability
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    immutable = Column(Boolean, default=True)

    # Relationships
    customer = relationship("Customer", back_populates="audit_logs")

    __table_args__ = (
        Index('ix_auditlog_customer_timestamp', 'customer_id', 'timestamp'),
        Index('ix_auditlog_resource', 'resource_type', 'resource_id'),
        Index('ix_auditlog_action', 'action'),
    )

    def update(self, **kwargs):
        """Prevent modifications to audit logs."""
        raise ValueError("Audit logs are immutable and cannot be modified")

    def delete(self):
        """Prevent deletion of audit logs."""
        raise ValueError("Audit logs are immutable and cannot be deleted")


class CustomerFeatureFlags(Base):
    """Feature flags per customer (for gradual rollouts)."""
    __tablename__ = "customer_feature_flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)

    # Feature name (e.g., "garak_security_testing", "advanced_metrics")
    feature_name = Column(String(255), nullable=False)
    is_enabled = Column(Boolean, default=False)

    # Metadata
    enabled_at = Column(DateTime)
    disabled_at = Column(DateTime)
    metadata = Column(JSON)  # Additional config for the feature

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_featureflag_customer_feature', 'customer_id', 'feature_name'),
    )


class UsageMetrics(Base):
    """Track usage for billing and analytics."""
    __tablename__ = "usage_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)

    # Usage counters
    evaluations_count = Column(Integer, default=0)
    api_calls_count = Column(Integer, default=0)
    storage_bytes = Column(Integer, default=0)

    # Time period
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Cost calculation
    estimated_cost = Column(String(50))  # For future billing

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_usagemetrics_customer_period', 'customer_id', 'period_start', 'period_end'),
    )


class ComplianceCertification(Base):
    """Track compliance certifications."""
    __tablename__ = "compliance_certifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)

    # Certification type
    cert_type = Column(String(50), nullable=False)  # hipaa, soc2, gdpr, iso27001

    # Status
    status = Column(String(50), default="pending")  # pending, certified, expired, audit_required

    # Dates
    certified_date = Column(DateTime)
    expiration_date = Column(DateTime)
    last_audit_date = Column(DateTime)
    next_audit_date = Column(DateTime)

    # Details
    audit_report_url = Column(String(255))
    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_compliance_customer_type', 'customer_id', 'cert_type'),
        Index('ix_compliance_status', 'status'),
    )
