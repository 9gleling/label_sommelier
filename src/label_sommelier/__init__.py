import asyncio
from . import server


def main():
    """Entry point for label-sommelier CLI."""
    asyncio.run(server.main())


__all__ = ["main", "server"]
