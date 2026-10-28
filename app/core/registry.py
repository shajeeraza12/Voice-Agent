"""Domain registration.

A domain is a folder under app/domains/. Each one exposes a `DOMAIN` object.
main.py (the composition root) imports the domains it wants and registers them;
core code never imports a domain directly.
"""
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI

from app.core.tools import ToolFn, register_tool


@dataclass
class Domain:
    name: str
    router: APIRouter | None = None
    tools: dict[str, ToolFn] = field(default_factory=dict)


_DOMAINS: dict[str, Domain] = {}


def register_domain(app: FastAPI, domain: Domain) -> None:
    _DOMAINS[domain.name] = domain
    for tool_name, fn in domain.tools.items():
        register_tool(domain.name, tool_name, fn)
    if domain.router is not None:
        app.include_router(domain.router)


def domains() -> list[str]:
    return sorted(_DOMAINS)
