import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_telegramuser"),
    ]

    operations = [
        migrations.CreateModel(
            name="VocabularyWord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("word_en", models.CharField(max_length=255)),
                ("word_ru", models.CharField(max_length=255)),
                ("is_favorite", models.BooleanField(default=False)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vocabulary_words",
                        to="core.telegramuser",
                    ),
                ),
            ],
            options={
                "verbose_name": "Vocabulary word",
                "verbose_name_plural": "Vocabulary words",
            },
        ),
        migrations.AddConstraint(
            model_name="vocabularyword",
            constraint=models.UniqueConstraint(
                fields=("user", "word_en"),
                name="unique_word_en_per_user",
            ),
        ),
    ]
