from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("GEMINI_API_KEY not found")
    exit()

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="""
Generate a professional software development task name.

Filename:
start_tracker.py

Return only the task name.
"""
)

print("\nAI Response:")
print(response.text)