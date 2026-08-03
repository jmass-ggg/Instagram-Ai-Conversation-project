from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("price_reply", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="processedcomment",
            name="meta_error_code",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processedcomment",
            name="meta_error_subcode",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processedcomment",
            name="meta_fbtrace_id",
            field=models.CharField(blank=True, max_length=255, default=""),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="processedcomment",
            name="status",
            field=models.CharField(
                choices=[
                    ("received", "Received"),
                    ("ignored", "Ignored"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                    ("already_replied", "Already Replied"),
                ],
                default="received",
                max_length=20,
            ),
        ),
    ]
