"""Base class and registry for product sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any, ClassVar

from ..config import expand_env
from ..http import HttpClient
from ..models import Product, Search

_REGISTRY: dict[str, type[Source]] = {}


def register(kind: str) -> Callable[[type[Source]], type[Source]]:
    def decorator(cls: type[Source]) -> type[Source]:
        _REGISTRY[kind] = cls
        cls.kind = kind
        return cls
    return decorator


class Source(ABC):
    kind: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # Form description for the web UI: name, label, type (text|number|bool|select|secret|selectors|map),
    # plus optional required/default/help/choices.
    fields: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, name: str, options: dict[str, Any], http: HttpClient):
        self.name = name
        self.options = options
        self.http = http

    @abstractmethod
    def search(self, search: Search) -> Iterator[Product]:
        """Yield products for a search. Filtering is re-applied by the crawler,
        so sources only need to push filters server-side where that is cheap."""


def build_source(name: str, kind: str, options: dict[str, Any], http: HttpClient) -> Source:
    try:
        cls = _REGISTRY[kind]
    except KeyError:
        raise ValueError(f"source '{name}': unknown type '{kind}' (known: {sorted(_REGISTRY)})") from None
    # Secrets can be stored as ${ENV_VAR} references and are resolved only at runtime.
    return cls(name, expand_env(options), http)


def source_types() -> list[dict[str, Any]]:
    return [{"type": k, "label": c.label, "description": c.description, "fields": c.fields}
            for k, c in sorted(_REGISTRY.items())]
