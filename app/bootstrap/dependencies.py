from dataclasses import fields

from fastapi import Request
from starlette.datastructures import State

from app.bootstrap.container import AppContainer


_CONTAINER_FIELDS = frozenset(field.name for field in fields(AppContainer))


class WorkspaceState(State):
    """Keep legacy state reads and replacements on the same container fields."""

    def __getattr__(self, name: str):
        if name in _CONTAINER_FIELDS:
            return getattr(self.container, name)
        return super().__getattr__(name)

    def __setattr__(self, name: str, value) -> None:
        if name in _CONTAINER_FIELDS:
            setattr(self.container, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _CONTAINER_FIELDS:
            delattr(self.container, name)
        else:
            super().__delattr__(name)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container
