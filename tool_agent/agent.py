"""Tool Agent"""

from datetime import datetime

from google.adk.agents import Agent
from google.adk.tools import google_search


# Define additional tools
def get_current_time():
    """Get the current time in the format YYYY-MM-DD HH:MM:SS."""
    now = datetime.now()

    # format the time as a string
    formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")
    return {"current_time": formatted_time}


root_agent = Agent(
    name="tool_agent",
    description="An agent that provides various tools and utilities to users.",
    model="gemini-2.0-flash",
    instruction="""
you are a helpful assistant that can use following tools:
- google search
- get current time
""",
    tools=[google_search, get_current_time],
)
