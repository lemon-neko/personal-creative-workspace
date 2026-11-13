from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from sqlite3 import Connection

from app.agent_runtime.infrastructure.adapters.focus_adapter import FocusAdapter
from app.agent_runtime.infrastructure.sqlite.repositories import RuntimeRepository


@dataclass(frozen=True)
class SQLiteRepositories:
    runtime: RuntimeRepository
    focus: FocusAdapter


class SQLiteUnitOfWork:
    def __init__(self, connect: Callable[[], Connection]):
        self.connect = connect

    @contextmanager
    def __call__(self, *, write: bool = False) -> Iterator[SQLiteRepositories]:
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield SQLiteRepositories(RuntimeRepository(connection), FocusAdapter(connection))
