"""Locust load-test scenarios for the AI Assurance Platform.

Acceptance target (B1 SKU, Phase 1):
    25 RPS sustained for 10 min, p95 < 2 000 ms, zero errors.
    100 RPS target deferred to Phase 2 / S1 SKU.

Invocation:
    locust -f loadtests/locustfile.py --headless -u 25 -r 5 --run-time 10m \
        --host $LOCUST_TARGET

Environment variables:
    LOCUST_TARGET      Base URL of the running application (e.g. http://localhost:8000)
    LOCUST_SDK_KEY     Optional. When set, HMAC-signed headers are attached to every request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from locust import HttpUser, between, task


def _hmac_headers(method: str, path: str, body: bytes, sdk_key: str) -> dict[str, str]:
    """Return the HMAC authentication headers for a request.

    Computes the canonical signing string used by the platform SDK:
        {unix_ts}\\n{METHOD}\\n{path}\\n{sha256_hex(body)}

    Args:
        method: HTTP method, upper-case (e.g. "POST").
        path: Request path including query string (e.g. "/api/demo/run").
        body: Raw request body bytes.
        sdk_key: The SDK signing secret.

    Returns:
        Dict of headers to merge into the request.
    """
    unix_ts = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{unix_ts}\n{method.upper()}\n{path}\n{body_hash}"
    signature = hmac.new(sdk_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Timestamp": unix_ts,
        "X-Signature": signature,
    }


class AigovernUser(HttpUser):
    """Simulated user exercising the four primary endpoint groups.

    Task weights reflect realistic traffic distribution:
        - scrub_endpoint   60 % — highest volume, PII pipeline
        - policy_check     20 % — moderate volume, policy gate
        - framework_matrix 10 % — lower volume, governance UI
        - health           10 % — lightweight liveness probe
    """

    wait_time = between(0.1, 0.5)

    _sdk_key: str | None = os.environ.get("LOCUST_SDK_KEY")

    def _extra_headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        """Return auth headers if LOCUST_SDK_KEY is configured, else empty dict."""
        if self._sdk_key:
            return _hmac_headers(method, path, body, self._sdk_key)
        return {}

    @task(60)
    def scrub_endpoint(self) -> None:
        """POST /api/demo/run — PII pipeline (highest weight)."""
        path = "/api/demo/run"
        payload: dict[str, Any] = {
            "prompt": "Customer John Smith SSN 123-45-6789 email john.smith@example.com "
                      "requests account balance for card 4111-1111-1111-1111",
            "system_id": "sys-payments-001",
            "action": "llm_call",
        }
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        headers.update(self._extra_headers("POST", path, body))
        with self.client.post(path, data=body, headers=headers, catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")
            else:
                resp.success()

    @task(20)
    def policy_check(self) -> None:
        """GET /api/release-gates/{system_id} — policy gate check."""
        path = "/api/release-gates/sys-payments-001"
        headers = self._extra_headers("GET", path, b"")
        with self.client.get(path, headers=headers, catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")
            else:
                resp.success()

    @task(10)
    def framework_matrix(self) -> None:
        """GET /api/frameworks/matrix — coverage matrix query."""
        path = "/api/frameworks/matrix?systems=sys-payments-001"
        headers = self._extra_headers("GET", path, b"")
        with self.client.get(path, headers=headers, catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")
            else:
                resp.success()

    @task(10)
    def health(self) -> None:
        """GET /api/health — liveness probe (no auth required)."""
        with self.client.get("/api/health", catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")
            else:
                resp.success()
