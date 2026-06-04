from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TelegramUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telegram_id", models.BigIntegerField(unique=True)),
                ("username", models.CharField(blank=True, default="", max_length=255)),
            ],
            options={
                "verbose_name": "Telegram user",
                "verbose_name_plural": "Telegram users",
            },
        ),
    ]
