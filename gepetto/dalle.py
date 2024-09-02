import os
import base64
import io
from openai import OpenAI
from discord import File

async def generate_image(prompt, return_prompt=False):
    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1/")
    try:
        response = client.images.generate(
            prompt=prompt,
            n=1,
            # size="512x512",
            size="1024x1024",
            model="dall-e-3",
            response_format="b64_json",
        )
    except Exception as e:
        print(f"Dalle Error: {e}")
        return None, None if return_prompt else None
    try:
        image_data = response.data[0].b64_json
        image_prompt = response.data[0].revised_prompt
        # image_data = response['data'][0]['b64_json']
        image_bytes = base64.b64decode(image_data)
        image = io.BytesIO(image_bytes)
        discord_file = File(fp=image, filename=f'channel_summary.png')
        if return_prompt:
            return discord_file, image_prompt
        return discord_file
    except Exception as e:
        print(f"Dalle Error: {e}")
        return None, None if return_prompt else None
