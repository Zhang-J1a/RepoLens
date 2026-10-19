import unittest

from taskboard.models import Task
from unittest.mock import Mock
from taskboard.repository import TaskRepository
from taskboard.service import TaskService


class TestTaskService(unittest.TestCase):
    def setUp(self):
        self.repository = TaskRepository()
        self.notifier = Mock()
        self.service = TaskService(self.repository, self.notifier)

    def test_create_sends_notification(self):
        task = Task(id=1, title="Review", owner_id=7)
        result = self.service.create_task(task)
        self.assertIs(result, task)
        self.assertEqual(self.repository.get(1), task)
        self.notifier.send.assert_called_once_with(task)

    def test_create_can_skip_notification(self):
        task = Task(id=2, title="Draft", owner_id=7, notify=False)
        self.service.create_task(task)
        self.assertEqual(self.repository.get(2), task)

    def test_archive_hides_task_from_active_list(self):
        task = Task(id=3, title="Done", owner_id=7)
        self.service.create_task(task)
        self.service.archive_task(3)
        self.assertEqual(self.service.list_tasks(7), [])

    def test_archive_missing_task_returns_false(self):
        self.assertFalse(self.service.archive_task(404))
