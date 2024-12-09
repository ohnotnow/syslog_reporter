from pydantic import BaseModel
from pydantic_ai.result import Cost
from typing import Dict, Optional
import json
import sys
class Pricing(BaseModel):
    """
    Encapsulates the pricing information for a specific model.
    """
    model_name: str
    input_cost_per_1M: float  # Cost per 1M input tokens
    output_cost_per_1M: float  # Cost per 1M output tokens
    cached_cost_per_1M: Optional[float] = 0.0  # Cost per 1M cached tokens (if applicable)

def get_model_pricing():
    model_pricing = {}
    # model_prices.json is from https://github.com/AgentOps-AI/tokencost/blob/main/tokencost/model_prices.json
    with open('model_prices.json', 'r') as file:
        model_prices = json.load(file)
        for model_name, model_info in model_prices.items():
            if model_info.get('mode') != 'chat':
                continue
            model_has_required_keys = all(key in model_info for key in ['input_cost_per_token', 'output_cost_per_token'])
            if not model_has_required_keys:
                continue
            model_pricing[model_name] = Pricing(
                model_name=model_name,
                input_cost_per_1M=model_info['input_cost_per_token'] * 1_000_000,
                output_cost_per_1M=model_info['output_cost_per_token'] * 1_000_000,
                cached_cost_per_1M=model_info.get('cache_read_input_token_cost', 0.0) * 1_000_000 if model_info.get('cache_read_input_token_cost') else None
            )
    return model_pricing

def get_cost(model_name: str, cost_obj: Cost) -> float:
    """
    Calculates the total cost of an API request based on the model and token usage.

    Args:
        model_name (str): The name of the model (e.g., 'openai:gpt-4o-mini' or 'gpt-4o-mini').
        cost_obj (Cost): An instance of the pydantic_ai.Cost model containing token usage details.

    Returns:
        float: The total cost in USD.

    Raises:
        ValueError: If the model is not found or if audio tokens are used with an unsupported model.
    """
    # Normalize the model name by removing the 'openai:' prefix if present
    if model_name.startswith('openai:'):
        model_key = model_name[len('openai:'):]
    else:
        model_key = model_name

    # Retrieve the pricing information for the specified model
    pricing = get_model_pricing().get(model_key)
    if not pricing:
        raise ValueError(f"Model '{model_key}' not found in pricing.")

    # Extract token counts
    request_tokens = cost_obj.request_tokens
    response_tokens = cost_obj.response_tokens
    cached_tokens = cost_obj.details.get('cached_tokens', 0)

    # Calculate the cost for regular input tokens
    regular_input_tokens = max(request_tokens - cached_tokens, 0)
    input_cost = (regular_input_tokens / 1_000_000) * pricing.input_cost_per_1M

    # Calculate the cost for cached tokens
    cached_cost = (cached_tokens / 1_000_000) * pricing.cached_cost_per_1M

    # Calculate the cost for output tokens
    output_cost = (response_tokens / 1_000_000) * pricing.output_cost_per_1M

    # Sum up all the costs to get the total cost
    total_cost = input_cost + cached_cost + output_cost

    return total_cost

# Example Usage
if __name__ == "__main__":
    # Sample cost object based on your example
    cost_example = Cost(
        request_tokens=9559,
        response_tokens=1528,
        total_tokens=11087,
        details={
            'accepted_prediction_tokens': 0,
            'audio_tokens': 0,  # Assuming these are audio input tokens
            'reasoning_tokens': 0,
            'rejected_prediction_tokens': 0,
            'cached_tokens': 3200
        }
    )

    # Calculate the cost for the 'openai:gpt-4o-mini' model
    try:
        total_cost = get_cost('openai:gpt-4o-mini', cost_example)
        print(f"Total cost for 'openai:gpt-4o-mini': ${total_cost:.6f}")
    except ValueError as e:
        print(str(e))
