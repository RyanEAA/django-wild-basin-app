class PostgreSQLDataRouter:
    """Keep the parallel PostgreSQL schema isolated from the live SQLite app.

    During the parallel migration phase:
    - ``pgdata`` reads/writes/migrates only on the ``postgresql`` alias.
    - every other Django app continues to migrate only on ``default``.

    Django may still *report* skipped migrations as applied in the secondary
    database's ``django_migrations`` table. ``allow_migrate`` controls whether
    their schema operations actually run.
    """

    pg_app_label = "pgdata"
    pg_database_alias = "postgresql"
    default_database_alias = "default"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.pg_app_label:
            return self.pg_database_alias
        return self.default_database_alias

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.pg_app_label:
            return self.pg_database_alias
        return self.default_database_alias

    def allow_relation(self, obj1, obj2, **hints):
        obj1_is_pg = obj1._meta.app_label == self.pg_app_label
        obj2_is_pg = obj2._meta.app_label == self.pg_app_label

        # Relations are allowed only when both objects live on the same side
        # of the parallel migration boundary.
        if obj1_is_pg or obj2_is_pg:
            return obj1_is_pg and obj2_is_pg
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.pg_app_label:
            return db == self.pg_database_alias

        # While PostgreSQL is a parallel validation database, no legacy/core
        # application should create schema there.
        if db == self.pg_database_alias:
            return False

        # Conversely, pgdata never migrates into the existing SQLite DB.
        return db == self.default_database_alias
