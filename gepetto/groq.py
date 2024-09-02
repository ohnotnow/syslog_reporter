import os
import json
from groq import Groq
from gepetto.response import ChatResponse, FunctionResponse
class GroqModel():
    name = "RecipeThis"

    def __init__(self, model=None):
        if model is None:
            self.model = "llama3-70b-8192"
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        return (0.50 / 1000000) * token_count

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
        api_key = os.getenv("GROQ_API_KEY")
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
        )
        # print(str(response.choices[0].message))
        tokens = response.usage.total_tokens
        cost = (0.50 / 1000000) * tokens
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    async def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        raise NotImplementedError
class GroqModelSync():
    name = "ApplicantFitter"

    def __init__(self, model=None):
        if model is None:
            self.model = "llama3-70b-8192"
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        return (0.50 / 1000000) * token_count

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
        api_key = os.getenv("GROQ_API_KEY")
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            timeout=30,
        )
        # print(str(response.choices[0].message))
        tokens = response.usage.total_tokens
        cost = (0.50 / 1000000) * tokens
        message = str(response.choices[0].message.content)
        return ChatResponse(message, tokens, cost, model)

    def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        raise NotImplementedError
