import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_vocabularyword_card_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="WordPlaylist",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="word_playlists",
                        to="core.telegramuser",
                    ),
                ),
            ],
            options={
                "verbose_name": "Word playlist",
                "verbose_name_plural": "Word playlists",
                "ordering": ["name", "id"],
            },
        ),
        migrations.CreateModel(
            name="WordPlaylistItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                (
                    "playlist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="core.wordplaylist",
                    ),
                ),
                (
                    "word",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="playlist_items",
                        to="core.vocabularyword",
                    ),
                ),
            ],
            options={
                "verbose_name": "Word playlist item",
                "verbose_name_plural": "Word playlist items",
                "ordering": ["word__word_en", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="wordplaylist",
            constraint=models.UniqueConstraint(
                fields=("user", "name"),
                name="unique_playlist_name_per_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="wordplaylistitem",
            constraint=models.UniqueConstraint(
                fields=("playlist", "word"),
                name="unique_word_per_playlist",
            ),
        ),
    ]
