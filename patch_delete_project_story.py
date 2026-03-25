import re

with open('api.py', 'r') as f:
    content = f.read()

# Define the replacement
old_code = """        stmt = select(UserStory).where(
            UserStory.product_id == project_id,
            UserStory.source_requirement == parent_requirement
        )
        stories = session.exec(stmt).all()

        deleted_count = 0
        for story in stories:
            # Delete sprint mappings
            sprint_mappings = session.exec(select(SprintStory).where(SprintStory.story_id == story.story_id)).all()
            for sm in sprint_mappings:
                session.delete(sm)

            # Delete completion logs
            logs = session.exec(select(StoryCompletionLog).where(StoryCompletionLog.story_id == story.story_id)).all()
            for log in logs:
                session.delete(log)

            # Delete the story (cascades to Tasks per schema)
            session.delete(story)
            deleted_count += 1

        session.commit()"""

new_code = """        from sqlalchemy import delete

        # 1. Get the list of story IDs to delete
        stmt = select(UserStory.story_id).where(
            UserStory.product_id == project_id,
            UserStory.source_requirement == parent_requirement
        )
        story_ids = session.exec(stmt).all()

        deleted_count = len(story_ids)

        if story_ids:
            # When batch deleting, we must explicitly delete child records to satisfy foreign keys
            # since bulk delete operations bypass SQLAlchemy ORM-level cascades.
            # Chunking the IN clause is a good practice to avoid SQLite limits
            chunk_size = 500
            for i in range(0, len(story_ids), chunk_size):
                chunk_ids = story_ids[i:i + chunk_size]

                # Delete sprint mappings
                session.exec(delete(SprintStory).where(SprintStory.story_id.in_(chunk_ids)))

                # Delete completion logs
                session.exec(delete(StoryCompletionLog).where(StoryCompletionLog.story_id.in_(chunk_ids)))

                # Delete tasks (and potentially their execution logs if they exist)
                # First get task IDs to delete any task execution logs
                from agile_sqlmodel import Task, TaskExecutionLog
                task_ids_stmt = select(Task.task_id).where(Task.story_id.in_(chunk_ids))
                task_ids = session.exec(task_ids_stmt).all()
                if task_ids:
                    for j in range(0, len(task_ids), chunk_size):
                        task_chunk = task_ids[j:j + chunk_size]
                        session.exec(delete(TaskExecutionLog).where(TaskExecutionLog.task_id.in_(task_chunk)))

                # Now delete tasks
                session.exec(delete(Task).where(Task.story_id.in_(chunk_ids)))

                # Delete the stories
                session.exec(delete(UserStory).where(UserStory.story_id.in_(chunk_ids)))

        session.commit()"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('api.py', 'w') as f:
        f.write(content)
    print("Patch applied successfully.")
else:
    print("Failed to find the old code in api.py.")
