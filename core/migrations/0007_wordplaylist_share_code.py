import secrets
import string

import django.db.models.deletion
from django.db import migrations, models


def _generate_share_code(existing: set[str]) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if code not in existing:
            existing.add(code)
            return code


def populate_share_codes(apps, schema_editor):
    WordPlaylist = apps.get_model("core", "WordPlaylist")
    existing: set[str] = set()
    for playlist in WordPlaylist.objects.all().iterator():
        playlist.share_code = _generate_share_code(existing)
        playlist.save(update_fields=["share_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_word_playlists"),
    ]

    operations = [
        migrations.AddField(
            model_name="wordplaylist",
            name="share_code",
            field=models.CharField(db_index=True, max_length=12, null=True, unique=True),
        ),
        migrations.RunPython(populate_share_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="wordplaylist",
            name="share_code",
            field=models.CharField(db_index=True, max_length=12, unique=True),
        ),
    ]
