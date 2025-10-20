"""Question Answering Agent."""

import os

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

dotenv.load_dotenv()

print(os.getenv("OPEN_ROUTER_API_KEY"))

model = LiteLlm(
    model="openrouter/openai/gpt-5-nano", api_key=os.getenv("OPEN_ROUTER_API_KEY")
)

question_answering_agent = LlmAgent(
    name="question_answering_agent",
    model=model,
    description="Question Answering agent",
    instruction="""
    You are a helpful question answering assistant.
    Use the context provided to answer the user's questions.
    If the answer is not in the context, respond with 'I don't know'.
    Here is some context about the user to help you answer questions:
    Name: {user_name}
    Preferences: {favorite_topics}
    """,
)
