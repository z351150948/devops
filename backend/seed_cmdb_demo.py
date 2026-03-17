import os
import sys

import django

sys.path.append('d:/code/agdevops/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agdevops.settings')
django.setup()

from cmdb.demo_seed import seed_cmdb_demo


if __name__ == '__main__':
    seed_cmdb_demo()
