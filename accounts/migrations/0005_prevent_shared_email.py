# Protect Django's user table when two requests try to save the same email at once.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_notification"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    # SQLite checks both new accounts and email changes. Blank addresses and existing
    # addresses stay available for accounts created before this migration.
    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE INDEX accounts_email_key_idx ON auth_user (LOWER(TRIM(email)))",
                """
                CREATE TRIGGER accounts_email_unique_insert
                BEFORE INSERT ON auth_user
                WHEN TRIM(NEW.email) <> '' AND EXISTS (
                    SELECT 1 FROM auth_user
                    WHERE LOWER(TRIM(email)) = LOWER(TRIM(NEW.email))
                )
                BEGIN
                    SELECT RAISE(ABORT, 'This email address is already used by another account.');
                END
                """,
                """
                CREATE TRIGGER accounts_email_unique_update
                BEFORE UPDATE OF email ON auth_user
                WHEN TRIM(NEW.email) <> ''
                    AND LOWER(TRIM(NEW.email)) <> LOWER(TRIM(OLD.email))
                    AND EXISTS (
                        SELECT 1 FROM auth_user
                        WHERE LOWER(TRIM(email)) = LOWER(TRIM(NEW.email)) AND id <> OLD.id
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'This email address is already used by another account.');
                END
                """,
            ],
            reverse_sql=[
                "DROP TRIGGER accounts_email_unique_update",
                "DROP TRIGGER accounts_email_unique_insert",
                "DROP INDEX accounts_email_key_idx",
            ],
        ),
    ]
