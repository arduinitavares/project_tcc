"""Greeting Agent"""

from google.adk.agents import Agent

root_agent = Agent(
    name="greeting_agent",
    description="An agent that greets users based on the time of day.",
    model="gpt-4o-nano",
    instruction="""
you are a helpful assistant that greets users based on the time of day.
Ask for the user 's name and the current time, then provide an appropriate greeting.
""",
)
