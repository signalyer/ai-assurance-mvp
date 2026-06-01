"""Immutable audit logging for compliance (HIPAA, SOC2, GDPR)."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Dict
from functools import wraps
import hashlib

# Configure the audit logger ONLY — never call logging.basicConfig() here,
# because basicConfig() mutates the ROOT logger, which means every other
# module that calls logger.warning() without passing extra={"action": ...,
# "user_id": ..., "ip_address": ..., "resource": ...} crashes with
# KeyError: 'action'. That bug took down /api/demo/run end-to-end in prod
# on 2026-05-23 (Day-12 recovery, layer 4) — fix is to attach the custom
# format to a dedicated handler on the "audit" logger and set
# propagate=False so the records never hit the root formatter.
_AUDIT_FMT = (
    '%(asctime)s | %(levelname)s | %(action)s | %(user_id)s | '
    '%(ip_address)s | %(resource)s | %(message)s'
)
_audit_formatter = logging.Formatter(_AUDIT_FMT)

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False  # critical: don't leak to root

# Idempotent handler install — re-imports in tests won't duplicate.
if not any(getattr(h, "_is_audit_handler", False) for h in audit_logger.handlers):
    _file = logging.FileHandler('audit.log')
    _file.setFormatter(_audit_formatter)
    _file._is_audit_handler = True  # type: ignore[attr-defined]
    _stream = logging.StreamHandler()
    _stream.setFormatter(_audit_formatter)
    _stream._is_audit_handler = True  # type: ignore[attr-defined]
    audit_logger.addHandler(_file)
    audit_logger.addHandler(_stream)


class AuditLog:
    """Immutable audit trail for regulatory compliance."""

    def __init__(self):
        self.logs = []
        self.hashes = []  # For tamper detection

    def log_action(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
        details: Optional[str] = None,
    ) -> str:
        """
        Log an action with full context.

        Returns:
            Log ID (hash) for verification
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create immutable record
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "ip_address": ip_address,
            "before_state": before_state,
            "after_state": after_state,
            "details": details,
        }

        # Create hash (tamper-evident)
        log_string = json.dumps(log_entry, sort_keys=True)
        log_hash = hashlib.sha256(log_string.encode()).hexdigest()

        # Chain with previous hash (blockchain-like)
        previous_hash = self.hashes[-1] if self.hashes else "GENESIS"
        chained_hash = hashlib.sha256(
            f"{previous_hash}{log_hash}".encode()
        ).hexdigest()

        # Store
        self.logs.append(log_entry)
        self.hashes.append(chained_hash)

        # Log to file
        audit_logger.info(
            json.dumps(log_entry),
            extra={
                "action": action,
                "user_id": user_id,
                "ip_address": ip_address,
                "resource": f"{resource_type}:{resource_id}",
            }
        )

        return chained_hash

    def verify_integrity(self) -> bool:
        """Verify no logs have been tampered with."""
        if not self.logs:
            return True

        for i in range(len(self.logs)):
            entry = self.logs[i]
            log_string = json.dumps(entry, sort_keys=True)
            calculated_hash = hashlib.sha256(log_string.encode()).hexdigest()

            previous_hash = self.hashes[i - 1] if i > 0 else "GENESIS"
            expected_chained = hashlib.sha256(
                f"{previous_hash}{calculated_hash}".encode()
            ).hexdigest()

            if expected_chained != self.hashes[i]:
                return False

        return True

    def get_logs_for_period(self, start: datetime, end: datetime) -> list:
        """Get audit logs for a time period (for compliance reports)."""
        return [
            log for log in self.logs
            if start <= datetime.fromisoformat(log["timestamp"]) <= end
        ]

    def get_logs_for_user(self, user_id: str) -> list:
        """Get all actions by a specific user."""
        return [log for log in self.logs if log["user_id"] == user_id]

    def get_logs_for_resource(self, resource_type: str, resource_id: str) -> list:
        """Get all actions on a specific resource."""
        return [
            log for log in self.logs
            if log["resource_type"] == resource_type
            and log["resource_id"] == resource_id
        ]


# Global audit log instance
global_audit = AuditLog()


def audit_log(
    action: str,
    resource_type: str,
    get_resource_id=None,
    get_user_id=None,
    get_ip_address=None,
):
    """
    Decorator to automatically log function calls.

    Usage:
        @audit_log("update", "domain", get_resource_id=lambda args: args[0].id)
        def update_domain(domain):
            ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract context
            resource_id = get_resource_id(args, kwargs) if get_resource_id else None
            user_id = get_user_id(args, kwargs) if get_user_id else None
            ip_address = get_ip_address(args, kwargs) if get_ip_address else None

            # Get before state
            before_state = None
            if get_resource_id and hasattr(args[0], '__dict__'):
                before_state = dict(args[0].__dict__)

            # Execute function
            result = func(*args, **kwargs)

            # Get after state
            after_state = None
            if get_resource_id and hasattr(result, '__dict__'):
                after_state = dict(result.__dict__)

            # Log it
            global_audit.log_action(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                user_id=user_id,
                ip_address=ip_address,
                before_state=before_state,
                after_state=after_state,
            )

            return result

        return wrapper

    return decorator


def log_evaluation(
    model: str,
    domain: str,
    trace_id: str,
    eval_scores: Dict[str, Any],
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """Log an evaluation execution."""
    global_audit.log_action(
        action="evaluate",
        resource_type="evaluation",
        resource_id=trace_id,
        user_id=user_id,
        ip_address=ip_address,
        after_state={
            "model": model,
            "domain": domain,
            "scores": eval_scores,
        },
        details=f"Evaluated {model} on {domain} domain",
    )


def log_access(
    resource_type: str,
    resource_id: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    allowed: bool = True,
):
    """Log a resource access attempt."""
    global_audit.log_action(
        action="access_denied" if not allowed else "access",
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        ip_address=ip_address,
        details="Access denied" if not allowed else "Access allowed",
    )


def generate_compliance_report(start: datetime, end: datetime) -> Dict[str, Any]:
    """Generate compliance audit report (HIPAA/SOC2/GDPR)."""
    logs = global_audit.get_logs_for_period(start, end)

    # Aggregate by action type
    by_action = {}
    for log in logs:
        action = log["action"]
        by_action[action] = by_action.get(action, 0) + 1

    # Aggregate by resource type
    by_resource = {}
    for log in logs:
        resource_type = log["resource_type"]
        by_resource[resource_type] = by_resource.get(resource_type, 0) + 1

    # Access denied attempts (security indicator)
    denied = [log for log in logs if log["action"] == "access_denied"]

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total_actions": len(logs),
        "by_action": by_action,
        "by_resource": by_resource,
        "access_denied_count": len(denied),
        "integrity_verified": global_audit.verify_integrity(),
        "logs": logs,
    }


if __name__ == "__main__":
    # Test
    print("Testing audit logging...")

    # Log some actions
    global_audit.log_action(
        action="create",
        resource_type="domain",
        resource_id="healthcare-1",
        user_id="user-123",
        ip_address="192.168.1.1",
        after_state={"name": "Healthcare", "compliance": "HIPAA"},
    )

    global_audit.log_action(
        action="evaluate",
        resource_type="evaluation",
        resource_id="eval-456",
        user_id="user-123",
        ip_address="192.168.1.1",
        after_state={"model": "claude-3.5-sonnet", "domain": "healthcare"},
    )

    # Verify integrity
    integrity_ok = global_audit.verify_integrity()
    print(f"✓ Integrity verified: {integrity_ok}")

    # Generate report
    from datetime import timedelta

    report = generate_compliance_report(
        datetime.now(timezone.utc) - timedelta(hours=1),
        datetime.now(timezone.utc),
    )
    print(f"✓ Compliance report generated: {report['total_actions']} actions logged")
    print(f"  Actions by type: {report['by_action']}")
    print(f"  Integrity check: {report['integrity_verified']}")
