"""Small, dependency-free runtime for tool-using Soony agents."""

from .runtime import Agent, Team, Tool

__all__ = ["Agent", "Team", "Tool", "build_team"]


def __getattr__(name):
    if name == "build_team":
        from .team import build_team
        return build_team
    raise AttributeError(name)
