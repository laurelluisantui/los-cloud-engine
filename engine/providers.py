"""Model provider interface. OpenAI via Agents SDK is the initial production
provider; the interface is provider-neutral for future Claude/Grok workers.
Without OPENAI_API_KEY a deterministic dev provider is used (no spend, clearly
marked) so tests and local demos never fabricate AI output."""
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import config


@dataclass
class ProviderResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str


class DevProvider:
    """Deterministic stand-in. Never claims to be a real model."""
    name = "dev"

    def complete(self, instructions: str, input_text: str, model: Optional[str] = None,
                 json_output: bool = True) -> ProviderResult:
        words = max(len(instructions.split()), len(input_text.split()))
        payload = {
            "provider": "dev",
            "note": "No OPENAI_API_KEY configured; deterministic dev response.",
            "summary": input_text[:400],
        }
        text = json.dumps(payload)
        return ProviderResult(text=text, tokens_in=words, tokens_out=len(text.split()),
                              model=model or "dev-echo", provider=self.name)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: Optional[str] = None) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key or config.OPENAI_API_KEY)

    def complete(self, instructions: str, input_text: str, model: Optional[str] = None,
                 json_output: bool = True) -> ProviderResult:
        use_model = model or config.ENGINE_MODEL
        kwargs: Dict[str, Any] = {"model": use_model, "instructions": instructions,
                                  "input": input_text}
        if json_output:
            kwargs["text"] = {"format": {"type": "json_object"}}
        resp = self.client.responses.create(**kwargs)
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text=resp.output_text,
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            model=use_model, provider=self.name,
        )


def get_provider() -> Any:
    if config.OPENAI_API_KEY:
        return OpenAIProvider()
    return DevProvider()


# Rough cost table ($/1M tokens) for usage accounting; dev provider costs 0.
COST_PER_M = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    rates = COST_PER_M.get(model, (0.0, 0.0))
    return round((tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000, 6)
