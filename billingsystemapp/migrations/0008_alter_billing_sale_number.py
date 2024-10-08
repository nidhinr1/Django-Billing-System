# Generated by Django 5.0.7 on 2024-07-21 15:08

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billingsystemapp', '0007_alter_billing_sale_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='billing',
            name='sale_number',
            field=models.IntegerField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
