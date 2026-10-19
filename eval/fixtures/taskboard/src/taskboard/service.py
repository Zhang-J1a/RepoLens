from .models import Task


class TaskService:
    def __init__(self, repository, notifier):
        self.repository = repository
        self.notifier = notifier

    def create_task(self, task: Task) -> Task:
        self.repository.add(task)
        if task.notify:
            self.notifier.send(task)
        return task

    def list_tasks(self, owner_id: int) -> list[Task]:
        return self.repository.active_for_owner(owner_id)

    def archive_task(self, task_id: int) -> bool:
        return self.repository.archive(task_id)

    def get_task(self, task_id: int) -> Task | None:
        return self.repository.get(task_id)
