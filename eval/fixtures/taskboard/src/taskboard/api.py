from .models import Task


class TaskAPI:
    def __init__(self, service):
        self.service = service

    def post_task(self, task: Task) -> Task:
        return self.service.create_task(task)

    def get_tasks(self, owner_id: int) -> list[Task]:
        return self.service.list_tasks(owner_id)

    def delete_task(self, task_id: int) -> bool:
        return self.service.archive_task(task_id)

    def get_task(self, task_id: int) -> Task | None:
        return self.service.get_task(task_id)
