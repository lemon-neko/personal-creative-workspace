from collections.abc import Mapping
from sqlite3 import Connection


class Repository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def _rows(self, sql: str, cls, params: tuple = ()) -> tuple:
        rows = self.connection.execute(sql, params).fetchall()
        return tuple(cls(**dict(row)) for row in rows)

    def _insert(self, table: str, data: Mapping) -> None:
        columns = ",".join(data)
        placeholders = ",".join(f":{key}" for key in data)
        self.connection.execute(
            f"INSERT INTO {table}({columns}) VALUES({placeholders})", data
        )
