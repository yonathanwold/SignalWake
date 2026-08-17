import pytest

from app.config import Settings
from app.database import create_engine, init_db, session_factory


@pytest.fixture
async def db_factory():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", use_demo_data=False)
    engine = create_engine(settings)
    await init_db(engine)
    factory = session_factory(engine)
    yield factory
    await engine.dispose()
