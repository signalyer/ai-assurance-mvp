"""Multi-domain configuration system for AI Assurance Platform."""

import json
from pathlib import Path
from typing import Optional


class Domain:
    """Represents a domain configuration with prompts, context, and eval weights."""

    def __init__(
        self,
        name: str,
        description: str,
        prompt: str,
        context: list[str],
        eval_weights: dict[str, float],
        risk_rules: dict[str, float],
    ):
        self.name = name
        self.description = description
        self.prompt = prompt
        self.context = context
        self.eval_weights = eval_weights  # e.g., {"hallucination": 0.4, "pii_leakage": 0.6}
        self.risk_rules = risk_rules  # e.g., {"high_threshold": 3, "medium_threshold": 1}

    @classmethod
    def from_json(cls, json_path: str) -> "Domain":
        """Load domain from JSON file. Supports both v1 (prompt/context) and v2 (test_cases/regulatory_context) schemas."""
        path = Path(json_path)
        if not path.exists():
            raise FileNotFoundError(f"Domain config not found: {json_path}")

        with open(path) as f:
            data = json.load(f)

        # v2 schema: test_cases + regulatory_context (preferred)
        # v1 schema: prompt + context (legacy)
        # The Domain.prompt represents the *default* test case used by single-prompt APIs.
        if "test_cases" in data and data["test_cases"]:
            prompt = data["test_cases"][0]["prompt"]
        else:
            prompt = data.get("prompt", "")

        if "regulatory_context" in data:
            context = data["regulatory_context"]
        else:
            context = data.get("context", [])

        return cls(
            name=data["name"],
            description=data["description"],
            prompt=prompt,
            context=context,
            eval_weights=data.get("eval_weights", {}),
            risk_rules=data.get("risk_rules", {}),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "context": self.context,
            "eval_weights": self.eval_weights,
            "risk_rules": self.risk_rules,
        }


def load_domain(domain_name: str) -> Domain:
    """Load domain by name from domains/ directory."""
    domain_path = Path(__file__).parent / "domains" / f"{domain_name}.json"
    return Domain.from_json(str(domain_path))


def list_domains() -> list[str]:
    """List all available domains."""
    domains_dir = Path(__file__).parent / "domains"
    if not domains_dir.exists():
        return []
    return [f.stem for f in domains_dir.glob("*.json")]


if __name__ == "__main__":
    # Test
    try:
        domains = list_domains()
        print(f"Available domains: {domains}")
        if domains:
            domain = load_domain(domains[0])
            print(f"\nLoaded {domain.name}:")
            print(f"  Description: {domain.description}")
            print(f"  Prompt: {domain.prompt[:80]}...")
    except Exception as e:
        print(f"Error: {e}")
