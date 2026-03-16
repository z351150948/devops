from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PermissionDefinition, Role, UserGroup
from .services import ensure_builtin_rbac


User = get_user_model()


class RbacPermissionTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.dashboard_permission = PermissionDefinition.objects.get(code='ops.dashboard.view')
        self.user_view_permission = PermissionDefinition.objects.get(code='rbac.user.view')

    def test_group_role_grants_effective_permission(self):
        role = Role.objects.create(code='dashboard-viewer', name='Dashboard Viewer')
        role.permissions.add(self.dashboard_permission)
        group = UserGroup.objects.create(code='observers', name='Observers')
        group.roles.add(role)

        user = User.objects.create_user(username='observer', password='Admin@123456')
        group.users.add(user)
        self.client.force_login(user)

        response = self.client.get('/api/dashboard/stats/')
        self.assertEqual(response.status_code, 200)

        denied = self.client.get('/api/hosts/')
        self.assertEqual(denied.status_code, 403)

    def test_view_only_user_cannot_create_users(self):
        role = Role.objects.create(code='user-auditor', name='User Auditor')
        role.permissions.add(self.user_view_permission)

        user = User.objects.create_user(username='auditor', password='Admin@123456')
        role.users.add(user)
        self.client.force_login(user)

        list_response = self.client.get('/api/users/')
        self.assertEqual(list_response.status_code, 200)

        create_response = self.client.post(
            '/api/users/',
            {
                'username': 'blocked-user',
                'password': 'Admin@123456',
                'email': 'blocked@example.com',
            },
        )
        self.assertEqual(create_response.status_code, 403)
