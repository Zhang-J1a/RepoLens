from .models import Task


class TaskRepository:
    def __init__(self):
        self._items: dict[int, Task] = {}

    def add(self, task: Task) -> None:
        self._items[task.id] = task

    def get(self, task_id: int) -> Task | None:
        return self._items.get(task_id)

    def active_for_owner(self, owner_id: int) -> list[Task]:
        return [
            task
            for task in self._items.values()
            if task.owner_id == owner_id and not task.archived
        ]

    def archive(self, task_id: int) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        task.archived = True
        return True
