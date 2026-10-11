from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opis_id", models.CharField(db_index=True, max_length=32)),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("city", models.CharField(max_length=100)),
                ("state", models.CharField(db_index=True, max_length=2)),
                ("rack_id", models.CharField(blank=True, max_length=32)),
                ("price_per_gallon", models.DecimalField(decimal_places=6, max_digits=10)),
                ("latitude", models.FloatField(blank=True, db_index=True, null=True)),
                ("longitude", models.FloatField(blank=True, db_index=True, null=True)),
            ],
            options={"indexes": [models.Index(fields=["state", "price_per_gallon"], name="api_fuelsta_state_ae8c8b_idx")]},
        ),
    ]
