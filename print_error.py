from utils.task_metadata import TaskMetadata, serialize_task_metadata
from models.core import Task
t = Task(
    story_id=1,
    description="Obsolete task description",
    metadata_json=serialize_task_metadata(TaskMetadata())
)
print("metadata ok")
