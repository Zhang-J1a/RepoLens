# Task API

`post_task(task)` creates a task through the service and returns that task.

`get_tasks(owner_id)` lists active tasks for the requested owner.

`delete_task(task_id)` archives the task; it does not promise physical deletion.

`get_task(task_id)` returns a task when present, otherwise `None`.
