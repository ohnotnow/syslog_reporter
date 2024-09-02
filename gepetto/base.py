from enum import Enum

class Model(Enum):
    DEFAULT = ('default', 1000.0, 2000.0)

    @classmethod
    def get_default(cls):
        return cls.DEFAULT

class BaseModel():
    name = "BaseModel"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.DEFAULT.value[0]
        else:
            self.model = model

    def get_token_price(self, token_count, direction="output", model_engine=None):
        token_price_input = 0
        token_price_output = 0
        if model_engine is None:
            model_engine = self.model
        for model in Model:
            if model_engine == model.value[0]:
                token_price_input = model.value[1] / 1000000
                token_price_output = model.value[2] / 1000000
                break
        return round(token_price_output * token_count, 4)

    async def chat(self, messages, temperature=1.0, model=Model.DEFAULT.value[0], top_p=0.6):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        raise NotImplementedError("This method is not implemented for the base class.")

    async def function_call(self, messages = [], tools = [], temperature=0.7, model=Model.DEFAULT.value[0]):
        raise NotImplementedError("This method is not implemented for the base class.")

class BaseModelSync():
    name = "BaseModelSync"

    def __init__(self, model=None):
        if model is None:
            self.model = Model.DEFAULT.value[0]
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
        return round(token_price_output * token_count, 4)

    def chat(self, messages, temperature=1.0, model=Model.DEFAULT.value[0], top_p=1.0):
        """Chat with the model.

        Args:
            messages (list): The messages to send to the model.
            temperature (float): The temperature to use for the model.

        Returns:
            str: The response from the model.
            tokens: The number of tokens used.
            cost: The estimated cost of the request.
        """
        raise NotImplementedError("This method is not implemented for the base class.")

    def function_call(self, messages = [], tools = [], temperature=0.7, model=None):
        raise NotImplementedError("This method is not implemented for the base class.")
