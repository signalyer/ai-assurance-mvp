// alerts.bicep — 8 scheduled query rule (KQL) alerts for AI Assurance Platform.
// All alerts query the Log Analytics workspace linked to App Insights.
// Severity: 2 (Warning) for all rules.

@description('Resource ID of the Log Analytics workspace to query.')
param workspaceId string

@description('Azure region for the alert resources.')
param location string

@description('Optional Action Group resource ID to notify on alert fire. Leave empty to skip.')
param actionGroupId string = ''

// ---------------------------------------------------------------------------
// Helper variable — action group array (empty when no action group provided)
// The scheduledQueryRules actions.actionGroups expects an array of strings
// (action group resource IDs), not objects.
// ---------------------------------------------------------------------------
var actionGroups = empty(actionGroupId) ? [] : [actionGroupId]

// ---------------------------------------------------------------------------
// 1. PII leak attempt — any increment in 5 min
// ---------------------------------------------------------------------------
resource alertPiiLeak 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-pii-leak'
  location: location
  properties: {
    displayName: 'PII Leak Attempt Detected'
    description: 'Fires when the pii_leak_attempt_total counter increments in any 5-minute window. Investigate injection guard logs immediately.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'customMetrics | where name == "pii_leak_attempt_total" | summarize TotalAttempts = sum(value) by bin(timestamp, 5m) | where TotalAttempts > 0'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 2. OPA unreachable — any increment in 5 min
// ---------------------------------------------------------------------------
resource alertOpaUnreachable 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-opa-unreachable'
  location: location
  properties: {
    displayName: 'OPA Policy Engine Unreachable'
    description: 'Fires when opa_unreachable_total increments — policy engine sidecar may be down. Default-DENY is active but audit coverage is degraded.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'customMetrics | where name == "opa_unreachable_total" | summarize TotalUnreachable = sum(value) by bin(timestamp, 5m) | where TotalUnreachable > 0'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Vault decryption errors — sum > 5 in 15 min
// ---------------------------------------------------------------------------
resource alertVaultError 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-vault-error'
  location: location
  properties: {
    displayName: 'De-ID Vault Decryption Errors Elevated'
    description: 'Fires when vault_error_total exceeds 5 in a 15-minute window. May indicate key rotation mismatch or corruption.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'customMetrics | where name == "vault_error_total" | summarize TotalErrors = sum(value) by bin(timestamp, 15m) | where TotalErrors > 5'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 4. Audit chain broken — any occurrence in 5 min
// ---------------------------------------------------------------------------
resource alertAuditChainBroken 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-audit-chain-broken'
  location: location
  properties: {
    displayName: 'Audit Chain Integrity Broken'
    description: 'Fires when audit_chain_break_total increments — tamper evidence violated. Immediate CISO escalation required.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'customMetrics | where name == "audit_chain_break_total" | summarize BreakCount = sum(value) by bin(timestamp, 5m) | where BreakCount > 0'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 5. HTTP 5xx rate > 1% in 5 min
// ---------------------------------------------------------------------------
resource alertHttp5xxRate 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-http-5xx-rate'
  location: location
  properties: {
    displayName: 'HTTP 5xx Error Rate Elevated'
    description: 'Fires when HTTP 5xx responses exceed 1% of total requests in a 5-minute window.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'requests | summarize TotalRequests = count(), ErrorRequests = countif(resultCode >= "500" and resultCode < "600") by bin(timestamp, 5m) | where TotalRequests > 0 | extend ErrorRate = todouble(ErrorRequests) / todouble(TotalRequests) | where ErrorRate > 0.01'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 6. p95 latency > 2000ms in 5 min
// ---------------------------------------------------------------------------
resource alertP95Latency 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-p95-latency'
  location: location
  properties: {
    displayName: 'p95 Request Latency Exceeds 2s'
    description: 'Fires when the 95th percentile of request duration exceeds 2000ms in a 5-minute window. Check for LLM call slowdowns or database lock contention.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'requests | summarize P95Duration = percentile(duration, 95) by bin(timestamp, 5m) | where P95Duration > 2000'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 7. RTF cascade PARTIAL_FAILURE in 5 min
// ---------------------------------------------------------------------------
resource alertRtfPartialFailure 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-rtf-partial-failure'
  location: location
  properties: {
    displayName: 'Right-to-Forget Cascade Partial Failure'
    description: 'Fires when an RTF cascade completes with PARTIAL_FAILURE status — some data stores may not have been purged. Manual verification of purge completeness required.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'customMetrics | where name == "rtf_cascade_total" | where tostring(customDimensions["status"]) == "PARTIAL_FAILURE" | summarize PartialFailures = sum(value) by bin(timestamp, 5m) | where PartialFailures > 0'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}

// ---------------------------------------------------------------------------
// 8. Scrub rate regression — scrubs/requests < 0.5 in 30 min
// ---------------------------------------------------------------------------
resource alertScrubRateRegression 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-scrub-rate-regression'
  location: location
  properties: {
    displayName: 'PII Scrub Rate Regression Detected'
    description: 'Fires when the ratio of scrub_pii_detected_total to total requests drops below 0.5 in a 30-minute window — possible bypass or scrubber misconfiguration.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT10M'
    windowSize: 'PT30M'
    scopes: [workspaceId]
    criteria: {
      allOf: [
        {
          query: 'let ScrubEvents = customMetrics | where name == "scrub_pii_detected_total" | summarize TotalScrubs = sum(value) by bin(timestamp, 30m); let RequestEvents = requests | summarize TotalRequests = count() by bin(timestamp, 30m); ScrubEvents | join kind=leftouter RequestEvents on timestamp | where TotalRequests > 10 | extend ScrubRate = todouble(TotalScrubs) / todouble(TotalRequests) | where ScrubRate < 0.5'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: actionGroups
    }
  }
}
