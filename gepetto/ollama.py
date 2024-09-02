import os
import json
from openai import OpenAI
from gepetto.response import ChatResponse, FunctionResponse

class OllamaModel():
    name = "Servalan"

    def __init__(self, model=None):
        if model is None:
            self.model = "dolphin-mistral"
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        return 0

    async def chat(self, messages, temperature=1.1, model=None):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        if model is None:
            model = self.model
        client = OpenAI(
            base_url = 'http://host.docker.internal:11434/v1',
            api_key='ollama', # required, but unused
        )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        tokens = input_tokens + output_tokens
        cost = 0
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    async def function_call(self, messages = [], tools = [], temperature=0.7, model="mistralai/Mistral-7B-Instruct-v0.1"):
        raise NotImplementedError

class OllamaModelSync():
    name = "Servalan"

    def __init__(self, model=None):
        if model is None:
            self.model = "dolphin-mistral"
        else:
            self.model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        return 0

    def chat(self, messages, temperature=1.1, model=None):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        if model is None:
            model = self.model
        client = OpenAI(
            base_url = 'http://localhost:11434/v1',
            api_key='ollama', # required, but unused
        )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        tokens = input_tokens + output_tokens
        cost = 0
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        raise NotImplementedError
