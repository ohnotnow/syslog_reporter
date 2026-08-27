"""Shared LiteLLM entry point for every LLM-calling agent.

Importing `completion` from here instead of litellm gives one place to
inject cross-cutting call options. Currently: SYSLOG_REASONING_EFFORT
(e.g. 'low' | 'medium' | 'high') is passed as reasoning_effort to
models that support it, handy for cheap/fast runs while testing.
Unset means the call is exactly litellm's default.
"""

import os

from litellm import completion as _completion


def completion(*args, **kwargs):
    effort = os.getenv("SYSLOG_REASONING_EFFORT")
    if effort and "reasoning_effort" not in kwargs:
        kwargs["reasoning_effort"] = effort
    return _completion(*args, **kwargs)
