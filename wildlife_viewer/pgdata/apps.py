from django.apps import AppConfig


class PgdataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pgdata"
    verbose_name = "PostgreSQL Wildlife Data"
