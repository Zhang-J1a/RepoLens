from service import TaskService


def test_create_task():
    assert TaskService().create_task("Read code")["title"] == "Read code"
