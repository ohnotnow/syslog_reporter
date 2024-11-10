import os
import json
from enum import Enum
from openai import OpenAI
from gepetto.response import ChatResponse, FunctionResponse

class Model(Enum):
    GPT4_32k = ('gpt-4-32k', 0.03, 0.06)
    GPT_4_1106_PREVIEW = ('gpt-4-1106-preview', 0.01, 0.03)
    GPT_4_TURBO = ('gpt-4-turbo', 0.01, 0.03)
    GPT_4_OMNI_MINI = ('gpt-4o-mini', 0.000150, 0.000075)
    GPT_4_OMNI_0806 = ('gpt-4o-2024-08-06', 0.00250, 0.01)
    GPT_4_OMNI = ('gpt-4o', 0.005, 0.015)
    GPT4 = ('gpt-4', 0.06, 0.12)
    GPT3_5_Turbo_gpt_1106 = ('gpt-3.5-turbo-1106', 0.001, 0.002)
    GPT3_5_Turbo_16k = ('gpt-3.5-turbo-16k', 0.003, 0.004)
    GPT3_5_Turbo = ('gpt-3.5-turbo', 0.0015, 0.002)

    @classmethod
    def get_default(cls):
        return cls.GPT_4_OMNI_0806

class GPTModel():
    name = "Gepetto"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.get_default().value[0]
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        token_price_input = 0
        token_price_output = 0
        if model_engine is None:
            model_engine = self.model
        for model in Model:
            if model_engine == model.value[0]:
                token_price_input = model.value[1] / 1000
                token_price_output = model.value[2] / 1000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    async def chat(self, messages, temperature=1.0, model=None, top_p=0.6, json_format=False):
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
        if json_format:
            format = {"type": "json_object"}
        else:
            format = {"type": "text"}
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = "https://api.openai.com/v1/"
        client = OpenAI(api_key=api_key, base_url=api_base)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            response_format=format,
        )
        # print(str(response.choices[0].message))
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        tokens = input_tokens + output_tokens
        output_cost = self.get_token_price(output_tokens, "output", model)
        input_cost = self.get_token_price(input_tokens, "input", model)
        cost = input_cost + output_cost
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    async def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        if model is None:
            model = self.model
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = "https://api.openai.com/v1/"
        client = OpenAI(api_key=api_key, base_url=api_base)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": tools[0]["function"]["name"]}},
        )
        # print(str(response.choices[0].message))
        tokens = response.usage.total_tokens
        cost = self.get_token_price(tokens, "output", model)
        message = response.choices[0].message
        parameters = json.loads(message.tool_calls[0].function.arguments)
        return FunctionResponse(parameters, tokens, cost)

class GPTModelSync():
    name = "Gepetto"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.get_default().value[0]
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        if model_engine is None:
            model_engine = self.model
        token_price_input = 0
        token_price_output = 0
        for model in Model:
            if model_engine ==model.value[0]:
                token_price_input = model.value[1] / 1000
                token_price_output = model.value[2] / 1000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    def chat(self, messages, temperature=1.0, model=None, top_p=1.0, json_format=False):
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
        if json_format:
            format = {"type": "json_object"}
        else:
            format = {"type": "text"}

        api_key = os.getenv("OPENAI_API_KEY")
        api_base = "https://api.openai.com/v1/"
        client = OpenAI(api_key=api_key, base_url=api_base)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        # print(str(response.choices[0].message))
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        tokens = input_tokens + output_tokens
        output_cost = self.get_token_price(output_tokens, "output", model)
        input_cost = self.get_token_price(input_tokens, "input", model)
        cost = input_cost + output_cost
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        if model is None:
            model = self.model
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = "https://api.openai.com/v1/"
        client = OpenAI(api_key=api_key, base_url=api_base)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": tools[0]["function"]["name"]}},
        )
        # print(str(response.choices[0].message))
        tokens = response.usage.total_tokens
        cost = self.get_token_price(tokens, "output", model)
        message = response.choices[0].message
        parameters = json.loads(message.tool_calls[0].function.arguments)
        return FunctionResponse(parameters, tokens, cost)
