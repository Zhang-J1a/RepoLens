from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SRC = ROOT / "eval" / "fixtures" / "taskboard" / "src"
sys.path.insert(0, str(FIXTURE_SRC))

from taskboard.models import Task
from taskboard.repository import TaskRepository
from taskboard.service import TaskService


class FixtureBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.repository = TaskRepository()
        self.notifier = Mock()
        self.service = TaskService(self.repository, self.notifier)

    def test_default_task_is_stored_and_notified(self):
        task = Task(id=1, title="Review", owner_id=7)
        self.service.create_task(task)
        self.assertIs(self.repository.get(1), task)
        self.notifier.send.assert_called_once_with(task)

    def test_notification_can_be_disabled(self):
        task = Task(id=2, title="Draft", owner_id=7, notify=False)
        self.service.create_task(task)
        self.notifier.send.assert_not_called()

    def test_archive_preserves_record_but_hides_it_from_active_list(self):
        task = Task(id=3, title="Done", owner_id=7)
        self.service.create_task(task)
        self.assertTrue(self.service.archive_task(3))
        self.assertIs(self.repository.get(3), task)
        self.assertEqual(self.service.list_tasks(7), [])


if __name__ == "__main__":
    unittest.main()
