from google import genai
import os
from base64 import b64encode

from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None

image_path = r"C:\Users\user1\PycharmProjects\PythonProject\BE-Python\sample3.jpg"
with open(image_path, "rb") as image_file:
    encoded_image = b64encode(image_file.read()).decode('utf-8')

response = gemini.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        {"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}},
        "이미지에서 텍스트를 추출해줘."
    ],
)

print(response.text)




