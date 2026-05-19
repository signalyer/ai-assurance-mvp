# Enterprise AI Assurance Platform — Architecture & Design

**Status:** Phase 1 - Multi-Tenant Architecture Design  
**Last Updated:** 2026-05-19  
**Compliance:** HIPAA, SOC2, GDPR (by-design)  

---

## 1. Multi-Tenancy Model

### Tenant Isolation Strategy
**Database-level isolation** (most secure for regulated industries):
- Separate PostgreSQL schema per customer
- Row-level security (RLS) policies
- Encryption at rest (AES-256)
- Encrypted columns for sensitive data

### Architecture
```
┌─────────────────────────────────────────┐
│         Shared Infrastructure            │
│  (Auth, routing, monitoring)             │
└──────────────┬──────────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
┌───▼───┐  ┌──▼───┐  ┌──▼───┐
│Customer│  │Customer│  │Customer│
│   1    │  │   2    │  │   3    │
│ Schema │  │ Schema │  │ Schema │
└────────┘  └────────┘  └────────┘
```

### Data Isolation Guarantees
- Customer A cannot query Customer B's data (RLS + schema)
- Audit logs are immutable (prevent tampering)
- Encryption keys rotated quarterly
- Data residency options (US, EU, APAC)

---

## 2. Authentication & Authorization

### Authentication Methods

#### Option 1: OAuth2 (Web Dashboard)
- Google OAuth / Azure AD / Okta
- OpenID Connect (OIDC) for SSO
- Multi-factor authentication (MFA) enforced

#### Option 2: API Key (Programmatic Access)
- Scoped API keys (read-only, write, admin)
- Auto-rotated every 90 days
- Rate-limited per key

#### Option 3: Service Account (Server-to-Server)
- Signed JWTs
- Granular permission scopes
- Audit-logged every use

### Authorization (RBAC)

```
Customer
├── Owner (full access)
├── Admin (manage users, view all data)
├── Analyst (view data, run evaluations)
└── API (programmatic access with scope)
```

### User Model
```python
class User:
    id: UUID
    customer_id: UUID (tenant)
    email: str
    role: Role  # owner, admin, analyst
    mfa_enabled: bool
    last_login: datetime
    created_at: datetime
    auth_method: str  # oauth, api_key, service_account
```

---

## 3. Multi-Tenant Database Schema

### Core Tables (Shared Across All Tenants)

```sql
-- Public schema (not tenant-specific)
CREATE TABLE public.customers (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    industry VARCHAR(50) NOT NULL,  -- healthcare, financial_services
    deployment_type VARCHAR(50),     -- saas, on_prem, hybrid
    created_at TIMESTAMP,
    subscription_tier VARCHAR(50),   -- starter, professional, enterprise
    hipaa_enabled BOOLEAN DEFAULT FALSE,
    soc2_enabled BOOLEAN DEFAULT FALSE,
    gdpr_enabled BOOLEAN DEFAULT FALSE,
    data_residency VARCHAR(50)       -- us, eu, apac
);

CREATE TABLE public.users (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers(id),
    email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    last_login TIMESTAMP,
    created_at TIMESTAMP,
    UNIQUE(customer_id, email)
);

CREATE TABLE public.api_keys (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers(id),
    key_hash VARCHAR(255) NOT NULL,  -- bcrypt hash
    name VARCHAR(255),
    scope VARCHAR(255),              -- read, write, admin
    last_used TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP,
    rotated_at TIMESTAMP
);

CREATE TABLE public.audit_logs (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL,
    user_id UUID,
    action VARCHAR(255),             -- create, read, update, delete
    resource_type VARCHAR(50),       -- domain, trace, evaluation
    resource_id UUID,
    change_details JSONB,
    ip_address INET,
    user_agent TEXT,
    timestamp TIMESTAMP NOT NULL,
    immutable BOOLEAN DEFAULT TRUE
);
```

### Per-Tenant Schema (Separate for each customer)

```sql
-- Customer-specific schema: customer_abc123
CREATE SCHEMA customer_abc123;

CREATE TABLE customer_abc123.domains (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    prompt TEXT NOT NULL,
    context JSONB,
    eval_weights JSONB,
    risk_rules JSONB,
    version INT DEFAULT 1,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    created_by UUID
);

CREATE TABLE customer_abc123.runs (
    id UUID PRIMARY KEY,
    domain_id UUID NOT NULL,
    model VARCHAR(100),
    prompt TEXT,
    response TEXT,
    latency_ms INT,
    tokens_used INT,
    status VARCHAR(50),              -- pending, running, complete, failed
    created_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB
);

CREATE TABLE customer_abc123.evaluations (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    metric_name VARCHAR(100),
    score FLOAT,
    passed BOOLEAN,
    skipped BOOLEAN,
    details TEXT,
    created_at TIMESTAMP
);

CREATE TABLE customer_abc123.traces (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    langfuse_trace_id VARCHAR(255),
    created_at TIMESTAMP
);
```

### Security Guarantees

**Row-Level Security (PostgreSQL RLS)**
```sql
-- Only users from customer_abc123 can access their data
CREATE POLICY tenant_isolation ON customer_abc123.domains
    USING (current_setting('app.customer_id') = customer_id);
```

---

## 4. API Architecture

### RESTful API Endpoints

#### Authentication
```
POST /api/v1/auth/login              -- OAuth callback
POST /api/v1/auth/token              -- Get JWT
POST /api/v1/auth/refresh            -- Refresh JWT
POST /api/v1/auth/logout             -- Revoke tokens
```

#### Customer Management (Admin only)
```
POST   /api/v1/customers             -- Create customer
GET    /api/v1/customers/:id         -- Get customer details
PATCH  /api/v1/customers/:id         -- Update customer
DELETE /api/v1/customers/:id         -- Disable customer (soft delete)
```

#### User Management
```
GET    /api/v1/customers/:id/users   -- List users
POST   /api/v1/customers/:id/users   -- Invite user
PATCH  /api/v1/users/:id             -- Update user
DELETE /api/v1/users/:id             -- Remove user
```

#### API Keys
```
POST   /api/v1/api-keys              -- Create API key
GET    /api/v1/api-keys              -- List API keys
DELETE /api/v1/api-keys/:id          -- Revoke API key
POST   /api/v1/api-keys/:id/rotate   -- Rotate key
```

#### Domains (Customer-specific)
```
GET    /api/v1/domains               -- List all domains
POST   /api/v1/domains               -- Create domain
GET    /api/v1/domains/:id           -- Get domain details
PATCH  /api/v1/domains/:id           -- Update domain
DELETE /api/v1/domains/:id           -- Archive domain
POST   /api/v1/domains/:id/versions  -- Get version history
```

#### Evaluations (Customer-specific)
```
POST   /api/v1/evaluate              -- Run evaluation
GET    /api/v1/evaluations           -- List evaluations
GET    /api/v1/evaluations/:id       -- Get evaluation details
GET    /api/v1/evaluations/:id/report -- Get PDF report
```

#### Usage & Analytics
```
GET    /api/v1/usage                 -- Get usage metrics
GET    /api/v1/usage/by-domain       -- Usage per domain
GET    /api/v1/compliance-report     -- Generate compliance report
```

---

## 5. Compliance by Design

### HIPAA (Healthcare)

**Required Controls:**
- Audit logging (all access logged)
- Encryption at rest (AES-256)
- Encryption in transit (TLS 1.3)
- Access controls (RBAC)
- Data retention policies
- Breach notification procedures

**Implementation:**
```python
class HIPAACompliance:
    @staticmethod
    def audit_log(customer_id, action, resource, user_id, ip):
        # Immutable audit trail
        AuditLog.create(
            customer_id=customer_id,
            action=action,
            resource_type=resource.__class__.__name__,
            resource_id=resource.id,
            user_id=user_id,
            ip_address=ip,
            timestamp=datetime.utcnow(),
            immutable=True
        )
    
    @staticmethod
    def encrypt_pii(data):
        # Encrypt sensitive fields
        return fernet.encrypt(data.encode())
    
    @staticmethod
    def enforce_access_control(user, resource):
        # Verify user has permission
        if user.customer_id != resource.customer_id:
            raise PermissionDenied()
```

### SOC2 (Financial Services)

**Required Controls:**
- Change management (track all changes)
- Incident response procedures
- Configuration management
- Physical security (data center)
- System monitoring

**Implementation:**
```python
@audit_log
def change_domain(domain_id, changes):
    """All changes automatically logged"""
    domain = Domain.get(domain_id)
    domain.update(changes)  # audit_log decorator captures this
    return domain
```

### GDPR (EU customers)

**Required Controls:**
- Data subject rights (access, deletion, portability)
- Consent management
- Data processing agreements (DPA)
- Privacy by design
- Data residency (EU only)

**Implementation:**
```python
class GDPRCompliance:
    @staticmethod
    def export_user_data(user_id):
        """GDPR right to data portability"""
        # Export all user's data as JSON
        return {
            "profile": user.to_dict(),
            "evaluations": user.evaluations.to_json(),
            "audit_logs": user.related_logs.to_json()
        }
    
    @staticmethod
    def delete_user_data(user_id, reason):
        """GDPR right to be forgotten"""
        user = User.get(user_id)
        user.delete(reason)  # Soft delete, immutable reason
```

---

## 6. Deployment Models

### SaaS Deployment (AWS/Azure)

**Architecture:**
```
Load Balancer
    ↓
API Gateway (rate limiting, auth)
    ↓
Kubernetes Cluster (auto-scaling)
    ├─ API Pods (stateless)
    ├─ Worker Pods (evaluations)
    └─ Scheduler (background jobs)
    ↓
PostgreSQL (multi-tenant)
    ├─ Shared schema (customers, users, audit)
    └─ Per-tenant schemas (encrypted)
    ↓
Redis (caching, sessions)
CloudWatch (monitoring, alerts)
```

**Scaling Characteristics:**
- Horizontal scaling (add more API pods)
- Auto-scaling based on CPU/memory
- Database connection pooling (pgbouncer)
- Request caching (Redis)

### On-Premise Deployment (Docker/Kubernetes)

**Architecture:**
```
Customer's Infrastructure (air-gapped optional)
    ↓
Docker Compose (single server) OR Kubernetes (multi-node)
    ├─ API Container
    ├─ Worker Container
    └─ PostgreSQL Container
    ↓
Customer's Network (no external traffic required)
```

**Deployment:**
```bash
# Single server
docker-compose -f docker-compose.on-prem.yml up

# Kubernetes
helm install ai-assurance ./charts/ai-assurance
```

---

## 7. Data Encryption Strategy

### Encryption at Rest
```python
class EncryptionManager:
    def __init__(self, master_key_path):
        self.cipher = Fernet(master_key_path)
    
    def encrypt_field(self, value):
        """Encrypt sensitive fields in database"""
        return self.cipher.encrypt(value.encode())
    
    def decrypt_field(self, encrypted_value):
        """Decrypt on read"""
        return self.cipher.decrypt(encrypted_value).decode()

# Usage in model
class Domain(Base):
    prompt = Column(String)  # Encrypted via SQLAlchemy hook
    context = Column(String)  # Encrypted
```

### Encryption in Transit
- TLS 1.3 for all APIs
- Certificate pinning for critical endpoints
- mTLS for service-to-service communication

### Key Management
- AWS KMS / Azure Key Vault for key storage
- Automatic key rotation (quarterly)
- Separate keys per environment (prod, staging, dev)

---

## 8. Audit & Logging

### Immutable Audit Trail

Every action is logged and cannot be modified:

```python
class AuditLog(Base):
    id = Column(UUID, primary_key=True)
    customer_id = Column(UUID, nullable=False)
    user_id = Column(UUID)  # Who did it
    action = Column(String)  # what (create, read, update, delete)
    resource_type = Column(String)  # Domain, Run, Evaluation
    resource_id = Column(UUID)  # Which resource
    before_state = Column(JSON)  # Previous values
    after_state = Column(JSON)   # New values
    ip_address = Column(String)  # From where
    user_agent = Column(String)  # What client
    timestamp = Column(DateTime) # When
    immutable = Column(Boolean, default=True)  # Cannot be deleted
    
    # Prevent modifications
    def update(self, **kwargs):
        raise ImmutableError("Audit logs cannot be modified")
```

### Compliance Reports

Generate audit reports for compliance audits:

```python
def generate_hipaa_audit_report(customer_id, start_date, end_date):
    logs = AuditLog.filter(
        customer_id=customer_id,
        timestamp__gte=start_date,
        timestamp__lte=end_date
    )
    
    return {
        "access_logs": logs.filter(action="read"),
        "modification_logs": logs.filter(action__in=["create", "update", "delete"]),
        "failed_access_attempts": logs.filter(action="access_denied"),
        "user_activity": logs.group_by("user_id"),
        "report_generated_at": datetime.utcnow()
    }
```

---

## 9. Technology Stack

### Backend
- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL (multi-tenant)
- **Cache:** Redis
- **Auth:** OAuth2 + JWT + API Keys
- **Logging:** ELK Stack (Elasticsearch, Logstash, Kibana)
- **Monitoring:** Prometheus + Grafana

### Deployment
- **Container:** Docker
- **Orchestration:** Kubernetes (SaaS) / Docker Compose (On-Prem)
- **Cloud:** AWS + Azure (multi-cloud)
- **Infrastructure as Code:** Terraform

### Compliance
- **Encryption:** cryptography library (Python)
- **Key Management:** AWS KMS / Azure Key Vault
- **Audit:** PostgreSQL native + custom logging

---

## 10. Implementation Timeline

| Phase | Focus | Hours | Deliverable |
|-------|-------|-------|-------------|
| 1 | Multi-tenant DB, Auth, RBAC | 8 | Foundation complete |
| 2 | Healthcare domain configs | 5 | HIPAA-ready domains |
| 3 | Financial services configs | 5 | SOC2-ready domains |
| 4 | Enhanced metrics (Ragas) | 6 | Better evaluations |
| 5 | Adversarial testing (Garak) | 5 | Security testing |
| 6 | APIs & integrations | 6 | REST, gRPC, webhooks |
| 7 | SaaS & On-prem deployment | 8 | Production ready |
| 8 | Security hardening | 4 | Compliance certified |
| 9 | Analytics & reporting | 4 | Dashboard & reports |

**Total:** ~51 hours → Production-ready

---

## 11. Compliance Roadmap

### HIPAA (Healthcare Customers)
- [ ] Phase 1: Audit logging, encryption
- [ ] Phase 2: Access controls, MFA
- [ ] Phase 3: HIPAA BAA template
- [ ] Phase 4: Penetration testing
- [ ] Phase 5: Certification audit

### SOC2 (Financial Services)
- [ ] Phase 1: Change management logs
- [ ] Phase 2: Incident response procedures
- [ ] Phase 3: Configuration management
- [ ] Phase 4: Monitoring & alerting
- [ ] Phase 5: SOC2 Type II audit

### GDPR (EU Customers)
- [ ] Phase 1: Data export/deletion endpoints
- [ ] Phase 2: Consent management
- [ ] Phase 3: DPA templates
- [ ] Phase 4: Privacy impact assessment
- [ ] Phase 5: Data residency (EU only)

---

## Next: Implementation

Phase 1 will implement:
1. Multi-tenant database schema
2. Authentication (OAuth2 + API keys)
3. RBAC system
4. Audit logging
5. Customer management API
6. Encryption at rest

**Ready to start Phase 1 build.**
