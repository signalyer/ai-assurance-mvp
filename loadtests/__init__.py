"""Load-test harness package for the AI Assurance Platform.

Invoke individual microbenches directly:
    python -m loadtests.scrubber_perf
    python -m loadtests.opa_p95
    python -m loadtests.framework_coverage_perf

Run the Locust scenario:
    locust -f loadtests/locustfile.py --headless -u 25 -r 5 --run-time 10m --host $LOCUST_TARGET
"""
from __future__ import annotations
