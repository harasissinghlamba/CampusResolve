"""
Adds `purpose` (LOGIN / REGISTRATION) and `channel` (EMAIL / SMS) to
LoginOTP, so the same model backs both the login step and the new
registration-verification step, over either delivery channel.

Existing rows are backfilled to LOGIN/EMAIL, which is exactly what they
were before this migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_loginotp"),
    ]

    operations = [
        migrations.AddField(
            model_name="loginotp",
            name="purpose",
            field=models.CharField(
                choices=[("LOGIN", "Student login"), ("REGISTRATION", "Account registration")],
                default="LOGIN",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="loginotp",
            name="channel",
            field=models.CharField(
                choices=[("EMAIL", "Email"), ("SMS", "SMS")],
                default="EMAIL",
                max_length=10,
            ),
        ),
        migrations.AddIndex(
            model_name="loginotp",
            index=models.Index(
                fields=["user", "purpose", "consumed"],
                name="accounts_lo_user_id_7b3e21_idx",
            ),
        ),
    ]
