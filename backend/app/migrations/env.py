import os

from alembic import context
from sqlalchemy import create_engine

import app.assessment.models
import app.learning.models
import app.sandbox.models  # noqa: F401
from app.syllabus.models import Base

url = context.config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
