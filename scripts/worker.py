"""Dedicated worker process: python -m scripts.worker."""
import asyncio
from app.services.jobs import main
if __name__ == '__main__':
    asyncio.run(main())
