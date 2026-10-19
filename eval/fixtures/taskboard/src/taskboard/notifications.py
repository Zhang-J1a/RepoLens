class NotificationGateway:
    def __init__(self, timeout_seconds: float = 3.0):
        self.timeout_seconds = timeout_seconds

    def send(self, task):
        return f"task:{task.id}:{task.title}"
