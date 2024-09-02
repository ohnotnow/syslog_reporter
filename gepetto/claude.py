import os
import json
from enum import Enum
import anthropic
from gepetto.response import ChatResponse, FunctionResponse

class Model(Enum):
    CLAUDE_3_HAIKU = ('claude-3-haiku-20240229', 0.25, 1.25)
    CLAUDE_3_SONNET = ('claude-3-sonnet-20240229', 3.00, 15.00)
    CLAUDE_35_SONNET = ('claude-3-5-sonnet-20240620', 3.00, 15.00)
    CLAUDE_3_OPUS = ('claude-3-opus-20240307', 15.00, 75.00)

class ClaudeModel():
    name = "Minxie"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.CLAUDE_3_HAIKU.value[0]
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        if model_engine is None:
            model_engine = self.model
        token_price_input = 0
        token_price_output = 0
        for model in Model:
            if model_engine.startswith(model.value[0]):
                token_price_input = model.value[1] / 1000000
                token_price_output = model.value[2] / 1000000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    async def chat(self, messages, temperature=0.7, model=None):
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
        api_key = os.getenv("CLAUDE_API_KEY")
        client = anthropic.Anthropic(
            api_key=api_key,
        )
        claude_messages = []
        system_prompt = ""
        for message in messages:
            if message["role"] == "system":
                system_prompt = message["content"]
            else:
                claude_messages.append(message)
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            temperature=0,
            system=system_prompt,
            messages=claude_messages
        )
        print(response.content)
        tokens = response.usage.input_tokens + response.usage.output_tokens
        cost = self.get_token_price(tokens, "output", model) + self.get_token_price(response.usage.input_tokens, "input", model)
        message = str(response.content[0].text)
        return ChatResponse(message, tokens, cost, model)

    async def function_call(self, messages = [], tools = [], temperature=0.7, model="mistralai/Mistral-7B-Instruct-v0.1"):
        raise NotImplementedError

class ClaudeModelSync():
    name = "Screener"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.CLAUDE_3_HAIKU.value[0]
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        if model_engine is None:
            model_engine = self.model
        token_price_input = 0
        token_price_output = 0
        for model in Model:
            if model_engine.startswith(model.value[0]):
                token_price_input = model.value[1] / 1000000
                token_price_output = model.value[2] / 1000000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    def chat(self, messages, temperature=0.7, model=None):
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
        api_key = os.getenv("CLAUDE_API_KEY")
        client = anthropic.Anthropic(
            api_key=api_key,
        )
        claude_messages = []
        system_prompt = ""
        for message in messages:
            if message["role"] == "system":
                system_prompt = message["content"]
            else:
                claude_messages.append(message)
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            temperature=0.1,
            system=system_prompt,
            messages=claude_messages
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        cost = self.get_token_price(tokens, "output", model) + self.get_token_price(response.usage.input_tokens, "input", model)
        message = str(response.content[0].text)
        return ChatResponse(message, tokens, cost, model)

    def function_call(self, messages = [], tools = [], temperature=0.7, model="mistralai/Mistral-7B-Instruct-v0.1"):
        raise NotImplementedError
