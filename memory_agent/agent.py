"""Memory Agent Definition."""

from google.adk.agents import Agent
from google.adk.tools.tool_context import ToolContext


def add_reminder(reminder: str, tool_context: ToolContext) -> dict:
    """Add a new reminder to the user's reminder list.

    Args:
        reminder: The reminder text to add
        tool_context: Context for accessing and updating session state

    Returns:
        A confirmation message
    """
    # Get current reminders from state
    reminders = tool_context.state.get("reminders", [])

    # Add the new reminder
    reminders.append(reminder)

    # Update state with the new list of reminders
    tool_context.state["reminders"] = reminders

    return {
        "action": "add_reminder",
        "reminder": reminder,
        "message": f"Added reminder: {reminder}",
    }


def view_reminders(tool_context: ToolContext) -> dict:
    """View all current reminders.

    Args:
        tool_context: Context for accessing session state

    Returns:
        The list of reminders
    """
    # Get reminders from state
    reminders = tool_context.state.get("reminders", [])

    return {"action": "view_reminders", "reminders": reminders, "count": len(reminders)}


def update_reminder(index: int, updated_text: str, tool_context: ToolContext) -> dict:
    """Update an existing reminder.

    Args:
        index: The 1-based index of the reminder to update
        updated_text: The new text for the reminder
        tool_context: Context for accessing and updating session state

    Returns:
        A confirmation message
    """
    # Get current reminders from state
    reminders = tool_context.state.get("reminders", [])

    # Check if the index is valid
    if not reminders or index < 1 or index > len(reminders):
        return {
            "action": "update_reminder",
            "status": "error",
            "message": f"Could not find reminder at position {index}. Currently there are {len(reminders)} reminders.",
        }

    # Update the reminder (adjusting for 0-based indices)
    old_reminder = reminders[index - 1]
    reminders[index - 1] = updated_text

    # Update state with the modified list
    tool_context.state["reminders"] = reminders

    return {
        "action": "update_reminder",
        "index": index,
        "old_text": old_reminder,
        "updated_text": updated_text,
        "message": f"Updated reminder {index} from '{old_reminder}' to '{updated_text}'",
    }


def delete_reminder(index: int, tool_context: ToolContext) -> dict:
    """Delete a reminder.

    Args:
        index: The 1-based index of the reminder to delete
        tool_context: Context for accessing and updating session state

    Returns:
        A confirmation message
    """
    # Get current reminders from state
    reminders = tool_context.state.get("reminders", [])

    # Check if the index is valid
    if not reminders or index < 1 or index > len(reminders):
        return {
            "action": "delete_reminder",
            "status": "error",
            "message": f"Could not find reminder at position {index}. Currently there are {len(reminders)} reminders.",
        }

    # Remove the reminder (adjusting for 0-based indices)
    deleted_reminder = reminders.pop(index - 1)

    # Update state with the modified list
    tool_context.state["reminders"] = reminders

    return {
        "action": "delete_reminder",
        "index": index,
        "deleted_reminder": deleted_reminder,
        "message": f"Deleted reminder {index}: '{deleted_reminder}'",
    }


def update_user_name(name: str, tool_context: ToolContext) -> dict:
    """Update the user's name.

    Args:
        name: The new name for the user
        tool_context: Context for accessing and updating session state

    Returns:
        A confirmation message
    """
    # Get current name from state
    old_name = tool_context.state.get("user_name", "")

    # Update the name in state
    tool_context.state["user_name"] = name

    return {
        "action": "update_user_name",
        "old_name": old_name,
        "new_name": name,
        "message": f"Updated your name to: {name}",
    }


# Create a simple persistent agent
memory_agent = Agent(
    name="memory_agent",
    model="gemini-2.0-flash",
    description="A smart reminder agent with persistent memory",
    # CHANGED: Updated instructions for clarity and forcefulness
    instruction="""
    You are a friendly and helpful reminder assistant. You can manage a user's reminders and remember their name across conversations.

    **Core Rule: You MUST use the provided tools to answer questions about or modify the user's reminders or name. DO NOT answer from your internal memory or context.**

    **Your Capabilities:**
    - Add new reminders.
    - View all reminders.
    - Update existing reminders.
    - Delete reminders.
    - Update the user's name.

    **How to Interact with Reminders:**
    - **Adding:** When the user asks to add a reminder, extract the core task and use the `add_reminder` tool.
    - **Viewing:** To answer ANY question about the user's current reminders (e.g., "what are my reminders?", "do I have anything for tomorrow?"), you MUST call the `view_reminders` tool to get the most up-to-date list.
    - **Updating/Deleting by Index:** If the user refers to a reminder by its number, use that number as the index for the `update_reminder` or `delete_reminder` tool.
    - **Updating/Deleting by Content:** If the user refers to a reminder by its content, you MUST call `view_reminders` first to see the list, then use the correct index to call the update or delete tool.
    - **General Conversation:** Always be friendly and address the user by their name if you know it.
    """,
    tools=[
        add_reminder,
        view_reminders,
        update_reminder,
        delete_reminder,
        update_user_name,
    ],
)
