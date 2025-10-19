"""LiteLLM Dad Joke Agent"""

import os
import random

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

dotenv.load_dotenv()


model = LiteLlm(
    model="openrouter/openai/gpt-5-nano", api_key=os.getenv("OPEN_ROUTER_API_KEY")
)


def get_dad_joke():
    """Return a random dad joke."""
    dad_jokes = [
        "Why don't skeletons fight each other? They don't have the guts.",
        "What do you call cheese that isn't yours? Nacho cheese.",
        "Why did the scarecrow win an award? Because he was outstanding in his field.",
        "Why don't scientists trust atoms? Because they make up everything.",
        "What do you call fake spaghetti? An impasta.",
    ]
    return {"dad_joke": random.choice(dad_jokes)}


root_agent = Agent(
    name="dad_joke_agent",
    description="An agent that tells dad jokes to users.",
    model=model,
    instruction="""
you are a funny dad joke assistant that tells dad jokes to users.
Only use the tool 'get_dad_joke' to tell a dad joke.
""",
    tools=[get_dad_joke],
)
