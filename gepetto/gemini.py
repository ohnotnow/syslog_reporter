import os
import json
from enum import Enum
import google.generativeai as genai
from gepetto.response import ChatResponse, FunctionResponse

class Model(Enum):
    GEMINI_1_5_FLASH = ('gemini-1.5-flash', 0.00, 0.00)
    GEMINI_1_5_PRO = ('gemini-1.5-pro', 0.00, 0.00)
    GEMINI_1_5_PRO_EXP = ('gemini-1.5-pro-exp', 0.00, 0.00)

class GeminiModel():
    name = "Gemma"
    uses_logs = False
    model = 'gemini-1.5-flash'

    def get_token_price(self, token_count, direction="output", model_engine=None):
        token_price_input = 0
        token_price_output = 0
        if not model_engine:
            model_engine = self.model
        for model in Model:
            if model_engine == model.value[0]:
                token_price_input = model.value[1] / 1000000
                token_price_output = model.value[2] / 1000000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    async def chat(self, messages, temperature=0.7, model=None, json_mode=False, tools=[]):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        if not model:
            model = self.model
        system_prompt = os.getenv("DISCORD_BOT_DEFAULT_PROMPT", "You are a helpful assistant.")
        user_prompt = ""
        for message in messages:
            if message["role"] == "system":
                system_prompt = message["content"]
            if message["role"] == "user":
                user_prompt = message["content"]
        api_key = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        bot = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_prompt)
        response = bot.generate_content(
            user_prompt,
            safety_settings={
                'HATE': 'BLOCK_NONE',
                'HARASSMENT': 'BLOCK_NONE',
                'SEXUAL' : 'BLOCK_NONE',
                'DANGEROUS' : 'BLOCK_NONE'
            }
        )
        print(response.text)
        tokens = response.usage_metadata.prompt_token_count + response.usage_metadata.candidates_token_count
        cost = self.get_token_price(response.usage_metadata.prompt_token_count, "input", model) + self.get_token_price(response.usage_metadata.candidates_token_count, "output", model)
        message = str(response.text)
        return ChatResponse(message, tokens, cost, model)

    async def function_call(self, messages = [], tools = [], temperature=0.7, model="mistralai/Mistral-7B-Instruct-v0.1"):
        raise NotImplementedError


class GeminiModelSync():
    name = "Gemma"
    uses_logs = False
    model = 'gemini-1.5-flash'

    def get_token_price(self, token_count, direction="output", model_engine=None):
        token_price_input = 0
        token_price_output = 0
        if not model_engine:
            model_engine = self.model
        for model in Model:
            if model_engine == model.value[0]:
                token_price_input = model.value[1] / 1000000
                token_price_output = model.value[2] / 1000000
                break
        if direction == "input":
            return round(token_price_input * token_count, 4)
        return round(token_price_output * token_count, 4)

    def chat(self, messages, temperature=0.7, model=None, json_format=False, tools=[], system_prompt="You are a helpful assistant."):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        if not model:
            model = self.model
        user_prompt = ""
        for message in messages:
            if message["role"] == "system":
                system_prompt = message["content"]
            if message["role"] == "user":
                user_prompt = message["content"]
        api_key = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        bot = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_prompt)
        response = bot.generate_content(
            user_prompt,
            safety_settings={
                'HATE': 'BLOCK_NONE',
                'HARASSMENT': 'BLOCK_NONE',
                'SEXUAL' : 'BLOCK_NONE',
                'DANGEROUS' : 'BLOCK_NONE'
            }
        )
        print(response.text)
        tokens = response.usage_metadata.prompt_token_count + response.usage_metadata.candidates_token_count
        cost = self.get_token_price(response.usage_metadata.prompt_token_count, "input", model) + self.get_token_price(response.usage_metadata.candidates_token_count, "output", model)
        message = str(response.text)
        return ChatResponse(message, tokens, cost, model)

    def function_call(self, messages = [], tools = [], temperature=0.7, model="mistralai/Mistral-7B-Instruct-v0.1"):
        raise NotImplementedError

if __name__ == "__main__":
    gemini = GeminiModelSync()
    print(gemini.chat([{"role": "user", "content": "Hello, how are you?"}]))
