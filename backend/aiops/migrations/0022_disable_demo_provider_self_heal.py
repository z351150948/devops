"""
0022: 永久禁用 demo provider 「智能助手体验版」自修復
- 刪除 demo provider row（如果存在）
- 確保將來 fresh install + migrate 都唔會重建呢個 demo provider
- reverse 是 noop（冇得恢復 demo，因為已經禁咗）
"""
import os

from django.db import migrations


DEMO_PROVIDER_NAME = '智能助手体验版'


def remove_demo_provider(apps, schema_editor):
    Model = apps.get_model('aiops', 'AIOpsModelProvider')
    # idempotent：冇 demo row 都唔爆
    deleted_count, _ = Model.objects.filter(name=DEMO_PROVIDER_NAME).delete()
    if deleted_count:
        print(f'[0022] removed demo provider "{DEMO_PROVIDER_NAME}" ({deleted_count} row)')
    else:
        print(f'[0022] no demo provider found, skipping')


def reverse_noop(apps, schema_editor):
    # 永久禁用：reverse 唔還原 demo provider
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('aiops', '0021_remove_aiopsknowledgeenvironment_posture_environments'),
    ]

    operations = [
        migrations.RunPython(remove_demo_provider, reverse_noop),
    ]