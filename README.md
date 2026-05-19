# AI Assurance Platform MVP

A working MVP for AI assurance with three core components:
1. **Langfuse Instrumentation Wrapper** — trace and monitor LLM API calls in real-time
2. **DeepEval Evaluation Suite** — run five metrics to measure output quality
3. **End-to-End Demo** — working example that ties both together

## Quick Start

### Prerequisites
- Python 3.11+
- API keys: Anthropic (Claude), OpenAI (for evaluators), Langfuse Cloud (public + secret key)

### Setup

1. **Clone and install:**
   ```bash
   cd ai-assurance-mvp
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and fill in your API keys
   ```

3. **Run the demo:**
   ```bash
   python demo.py
   ```

## Components

### 1. Langfuse Wrapper (`langfuse_wrapper.py`)

Lightweight wrapper around Langfuse Cloud for tracing LLM calls.

**Usage:**
```python
from langfuse_wrapper import LangfuseTracer

tracer = LangfuseTracer()

# Trace an LLM call
trace_id = tracer.trace_llm_call(
    function_name="my_llm_call",
    model="gpt-4",
    input_data={"prompt": "..."},
    output_data={"content": "..."},
)

# Log evaluation metrics
tracer.trace_evaluation(
    trace_id=trace_id,
    metric_name="accuracy",
    metric_value=0.95,
    passed=True,
    details={"reasoning": "..."},
)

tracer.flush()
```

**Features:**
- Automatic client initialization from env vars
- Simple `trace_llm_call()` for logging API calls
- `trace_evaluation()` for attaching metrics
- Runs standalone: `python langfuse_wrapper.py`

### 2. Evaluation Suite (`eval_suite.py`)

Five core metrics from DeepEval for measuring LLM output quality.

**Metrics:**
1. **Relevance** — Is the output relevant to the input?
2. **Coherence** — Is the output logically structured?
3. **Faithfulness** — Is the output faithful to provided context?
4. **Correctness** — Is the output factually correct?
5. **Toxicity** — Does the output contain harmful content?

**Usage:**
```python
from eval_suite import EvaluationSuite

suite = EvaluationSuite()

results = suite.evaluate_output(
    input_text="What is 2+2?",
    actual_output="The answer is 4.",
    retrieval_context=["Math fact: 2+2=4"],
    expected_output="4",
)

for metric, result in results.items():
    print(f"{metric}: {result['score']:.2f} - {result['passed']}")

summary = suite.summarize_results(results)
print(f"Passed: {summary['passed_count']}/{summary['total_count']}")
```

**Features:**
- Five distinct evaluators
- Threshold-based pass/fail logic
- Error handling for each metric
- Aggregated summary reporting
- Runs standalone: `python eval_suite.py`

### 3. End-to-End Demo (`demo.py`)

Complete working example that:
- Generates a response using Claude API
- Traces it with Langfuse
- Evaluates it with all 5 metrics
- Logs metrics back to Langfuse
- Displays results

**Run it:**
```bash
python demo.py
```

**Output:**
- Real LLM response generation
- 5 metric scores with pass/fail status
- Summary of evaluation
- Langfuse trace URL for inspection

## Files

```
ai-assurance-mvp/
├── langfuse_wrapper.py      # Tracing instrumentation
├── eval_suite.py            # 5-metric evaluation suite
├── demo.py                  # End-to-end working example
├── requirements.txt         # Dependencies
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

## Architecture

```
LLM API Call
    ↓
Langfuse Tracer (trace_llm_call)
    ↓ [trace_id]
Evaluation Suite (evaluate_output)
    ↓
5 Metrics (relevance, coherence, faithfulness, correctness, toxicity)
    ↓
Langfuse Tracer (trace_evaluation) — log metrics back
    ↓
Langfuse Cloud — view traces & metrics
```

## Configuration

Required environment variables (see `.env.example`):

```
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
EVAL_MODEL=gpt-4o-mini
```

## Design Principles

- **No abstractions** — direct Langfuse and DeepEval APIs
- **Standalone files** — each can run independently with `python filename.py`
- **Type hints** — explicit types throughout
- **Docstrings** — every function documented
- **Error handling** — graceful failures with informative messages
- **No async** — synchronous for simplicity
- **Config via env** — no hardcoded values

## Next Steps

Once validated:
- Add more custom metrics (latency, cost, token usage)
- Build dashboard to view Langfuse traces
- Add batch evaluation mode for datasets
- Integrate into CI/CD for continuous evaluation
- Add cost tracking per trace

## Troubleshooting

**Missing API key error:**
- Ensure `.env` file exists and is filled in
- Use `cp .env.example .env` and add your keys

**Langfuse connection error:**
- Verify `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
- Confirm `LANGFUSE_HOST` is correct (default: `https://cloud.langfuse.com`)

**OpenAI evaluator errors:**
- Ensure `OPENAI_API_KEY` is set
- Verify you have quota available in your OpenAI account
- Try using `gpt-4o-mini` in `.env` (cheaper than full GPT-4)

**Claude API errors:**
- Confirm `ANTHROPIC_API_KEY` is valid
- Check your Anthropic account quota

## License

MIT
