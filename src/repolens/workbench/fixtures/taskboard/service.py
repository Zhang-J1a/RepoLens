"""Synthetic local demonstration data; never executed by RepoLens."""


class TaskRepository:
    def save(self, title):
        return {"title": title, "status": "open"}


class TaskService:
    def normalize_title(self, title):
        return title

    def create_task(self, title):
        normalized = self.normalize_title(title)
        return TaskRepository().save(normalized)


def create_task_endpoint(title):
    return TaskService().create_task(title)
