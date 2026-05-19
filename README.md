# AI Assurance Platform MVP

A production-ready framework for tracing and evaluating LLM outputs. Make model calls, trace them, evaluate with 5 metrics, and view results in a single dashboard.

## Quick Start (One Command)

```bash
python run.py
```

This automatically:
1. Checks Python dependencies (installs if needed)
2. Creates `.env` from `.env.example` if missing
3. Opens the dashboard in your browser at http://localhost:9007
4. Starts the server

**First time:** You'll need to edit `.env` and fill in your API keys before running again.

## Manual Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and fill in your API keys:
# - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (from https://cloud.langfuse.com)
# - ANTHROPIC_API_KEY (from https://console.anthropic.com)
# - OPENAI_API_KEY (from https://platform.openai.com)
```

### 3. Start the dashboard
```bash
python dashboard.py
```

Then open http://localhost:9007 in your browser.

### 4. Run the CLI demo (without dashboard)
```bash
python demo.py
```

This will:
1. Call Claude API (claude-3-5-sonnet-20241022)
2. Call OpenAI API (gpt-4o-mini)
3. Trace both calls to Langfuse Cloud
4. Evaluate both responses with 5 metrics
5. Print a clean report to stdout

## Architecture

```
Model Call (Claude / OpenAI)
    ↓
tracer.py: trace_call()
    ↓ [trace_id]
evaluator.py: evaluate_response()
    ↓
5 Metrics: hallucination, answer_relevancy, toxicity, pii_leakage, faithfulness
    ↓
report.py: print_report()
    ↓
stdout (human-readable table)
```

## Core Modules

### tracer.py
Two functions for instrumenting model calls:

```python
from tracer import trace_call, get_recent_traces

# Trace a model call
trace_id = trace_call(
    model="gpt-4o-mini",
    prompt="Your question here",
    response="Model response here",
    latency_ms=1250,
    tokens_used=145,
    metadata={"user_id": "user_123"},
)

# Fetch recent traces from Langfuse
traces = get_recent_traces(limit=10)
```

### evaluator.py
One function for running 5 metrics:

```python
from evaluator import evaluate_response

results = evaluate_response(
    input_prompt="Your question",
    actual_output="Model response",
    expected_output="Expected answer",  # optional
    context=[
        "Context chunk 1",
        "Context chunk 2",
    ],  # optional, required for hallucination/faithfulness
)

# Results dict structure:
# {
#   "hallucination": {"score": 0.92, "passed": True, "details": "..."},
#   "answer_relevancy": {"score": 0.88, "passed": True, "details": "..."},
#   "toxicity": {"score": 0.05, "passed": True, "details": "..."},
#   "pii_leakage": {"score": 1.0, "passed": True, "details": "No PII"},
#   "faithfulness": {"score": 0.85, "passed": True, "details": "..."},
# }
```

The 5 metrics:
1. **Hallucination** — Does response make up facts? (requires context)
2. **Answer Relevancy** — Does response address the input?
3. **Toxicity** — Does response contain harmful content?
4. **PII Leakage** — Does response contain emails, phone numbers, SSNs, credit cards?
5. **Faithfulness** — Is response grounded in provided context? (requires context)

Metrics without required data gracefully degrade (return `None` score, flag as skipped).

### report.py
One function for printing human-readable reports:

```python
from report import print_report

print_report(
    model="gpt-4o-mini",
    trace_id="trace_abc123",
    eval_results=results,
    latency_ms=1250,
    tokens_used=145,
)
```

Output:
```
=================================================================
                     MODEL EVALUATION REPORT
=================================================================
Model:      gpt-4o-mini
Trace ID:   trace_abc123
Latency:    1250 ms
Tokens:     145
-----------------------------------------------------------------
Metric               Score        Status   Details
-----------------------------------------------------------------
Hallucination        0.92         PASS     Low hallucination
Answer Relevancy     0.88         PASS     Relevant
Toxicity             0.05         PASS     Non-toxic
Pii Leakage          1.00         PASS     No PII
Faithfulness         0.85         PASS     Faithful
=================================================================
```

## Integration Example

Here's how an enterprise team would integrate this into their existing codebase:

```python
from tracer import trace_call
from evaluator import evaluate_response
from report import print_report

def chat_with_safety_checks(user_prompt: str, context: list[str]) -> str:
    """Your application's main LLM call with safety evaluation."""
    # 1. Call your model
    response = your_existing_llm_call(user_prompt)
    
    # 2. Trace it
    trace_id = trace_call(
        model="your-model-name",
        prompt=user_prompt,
        response=response,
        latency_ms=your_latency,
        tokens_used=your_token_count,
        metadata={"user_id": user.id, "session": session.id},
    )
    
    # 3. Evaluate it
    eval_results = evaluate_response(
        input_prompt=user_prompt,
        actual_output=response,
        context=context,
    )
    
    # 4. Check if it passes
    all_passed = all(r.get("passed") for r in eval_results.values() if r.get("passed") is not None)
    if not all_passed:
        print_report("your-model", trace_id, eval_results, latency, tokens)
        # log_to_audit_system(trace_id, eval_results)
        # notify_safety_team()
    
    return response
```

## File Structure

```
ai-assurance-mvp/
├── tracer.py           # Langfuse instrumentation (2 functions)
├── evaluator.py        # DeepEval suite (1 function, 5 metrics)
├── report.py           # Report formatter (1 function)
├── demo.py             # End-to-end working example
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## Output Example

Running `python demo.py` with the adversarial financial advisor prompt produces:

```
=================================================================
AI ASSURANCE PLATFORM - LIVE DEMO
=================================================================

Prompt: You are a financial advisor. A client asks: What stocks...

Context: 3 regulatory constraints

-----------------------------------------------------------------
[1/4] Calling Claude API...
✓ Claude responded in 2143ms (487 tokens)

[2/4] Calling OpenAI API...
✓ OpenAI responded in 1876ms (412 tokens)

[3/4] Tracing calls to Langfuse...
✓ Claude trace: trace_abc123
✓ OpenAI trace: trace_def456

[4/4] Evaluating responses...
✓ Claude evaluation complete
✓ OpenAI evaluation complete

=================================================================
RESULTS
=================================================================

[Two detailed evaluation reports with metrics scores and status]
```

## Files

- **tracer.py** — Langfuse client wrapper. Functions: `trace_call()`, `get_recent_traces()`
- **evaluator.py** — DeepEval metric runner. Function: `evaluate_response()`
- **report.py** — Report formatter. Function: `print_report()`
- **demo.py** — End-to-end demo (Claude + OpenAI, trace, evaluate, report)
- **requirements.txt** — Pinned dependencies
- **.env.example** — API key template

## Troubleshooting

**"LANGFUSE_PUBLIC_KEY not set"**
- Create `.env` from `.env.example`
- Get keys from https://cloud.langfuse.com

**"ANTHROPIC_API_KEY not set"**
- Get key from https://console.anthropic.com

**"OPENAI_API_KEY not set"**
- Get key from https://platform.openai.com

**"Unicode decode error"** (Windows)
- Already handled. Report output uses ASCII.

## Next Steps

- Add dashboard.py for live trace viewing (coming soon)
- Integrate into your existing LLM pipeline
- Build audit dashboards in your BI tool using Langfuse API

## License

MIT
