from dataclasses import dataclass


@dataclass
class Task:
    id: int
    title: str
    owner_id: int
    notify: bool = True
    archived: bool = False
