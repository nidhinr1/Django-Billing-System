# Generated by Django 5.0.7 on 2024-08-08 05:48

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billingsystemapp', '0015_billing_customer_address_billing_customer_name_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Customer',
        ),
    ]
