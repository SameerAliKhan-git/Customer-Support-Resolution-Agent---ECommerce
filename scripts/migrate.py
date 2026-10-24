"""Upgrade application schema, backing up legacy SQLite data before adoption."""
import datetime
import importlib.util
import sqlite3
from pathlib import Path
from sqlalchemy import inspect,create_engine
from alembic.config import Config
from alembic import command
from app.db.session import sync_engine

def main():
    inspector=inspect(sync_engine)
    tables=set(inspector.get_table_names())
    if sync_engine.dialect.name=='sqlite' and tables:
        source=Path(sync_engine.url.database).resolve()
        folder=source.parent/'backups';folder.mkdir(exist_ok=True)
        target=folder/(source.stem+'-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.db')
        with sqlite3.connect(source) as original,sqlite3.connect(target) as backup:
            original.backup(backup)
        print('SQLite backup:',target.name)
    cfg=Config('alembic.ini')
    versioned = False
    if 'alembic_version' in tables:
        with sync_engine.connect() as connection:
            versioned = bool(connection.exec_driver_sql('SELECT version_num FROM alembic_version').first())
    if tables and not versioned:
        # Adopt only a schema containing every frozen baseline table and column.
        spec=importlib.util.spec_from_file_location('baseline','migrations/versions/0001_initial.py')
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with create_engine('sqlite://').connect() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                baseline.upgrade()
            expected=inspect(conn)
            for table in expected.get_table_names():
                if table not in tables or not {c['name'] for c in expected.get_columns(table)} <= {c['name'] for c in inspector.get_columns(table)}:
                    raise RuntimeError('Legacy schema is not the recognized baseline; manual migration is required.')
        command.stamp(cfg,'0001')
    command.upgrade(cfg,'head')
    print('Application schema upgraded.')

if __name__=='__main__':main()
