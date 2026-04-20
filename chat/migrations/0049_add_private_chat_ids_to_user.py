# Generated migration for adding private_chat_ids to CustomUser

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0038_add_group_avatar'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='private_chat_ids',
            field=models.JSONField(
                blank=True, default=list, help_text='List of chat IDs marked as private by the user'),
        ),
    ]
