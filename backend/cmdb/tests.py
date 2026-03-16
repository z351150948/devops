from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import CIType, CIRelation, ConfigItem, CostRecord


class AuthenticatedTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser('cmdb-admin', 'cmdb@example.com', 'Admin@123456')
        self.client.force_login(self.user)


class CmdbCostAnalysisTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.current_month = timezone.now().strftime('%Y-%m')
        self.previous_month = (
            timezone.now().replace(day=1) - timezone.timedelta(days=1)
        ).strftime('%Y-%m')

        host_type = CIType.objects.create(name='Host')
        db_type = CIType.objects.create(name='Database')

        self.prod_ci = ConfigItem.objects.create(
            name='prod-db-01',
            ci_type=db_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'monthly_cost': 1200, 'cpu': 16, 'memory_gb': 32},
        )
        self.test_ci = ConfigItem.objects.create(
            name='test-host-01',
            ci_type=host_type,
            business_line='core',
            environment='test',
            status='active',
            attributes={'monthly_cost': 600, 'cpu': 8, 'memory_gb': 16},
        )
        self.idle_ci = ConfigItem.objects.create(
            name='idle-host-01',
            ci_type=host_type,
            business_line='shared',
            environment='prod',
            status='idle',
            attributes={'monthly_cost': 300, 'cpu': 4, 'memory_gb': 8},
        )
        CostRecord.objects.create(
            ci=self.prod_ci,
            month=self.previous_month,
            amount=Decimal('1000.00'),
            provider='history',
        )

    def test_cost_report_syncs_current_month_and_returns_aggregates(self):
        response = self.client.get('/api/cmdb/cost/report/', {'month': self.current_month})

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['month'], self.current_month)
        self.assertEqual(payload['total_monthly_cost'], 2100.0)
        self.assertEqual(
            CostRecord.objects.filter(month=self.current_month).count(),
            3,
        )
        self.assertEqual(payload['top_cost_items'][0]['name'], 'prod-db-01')
        self.assertEqual(payload['by_business'][0]['business_line'], 'core')
        self.assertEqual(payload['by_business'][0]['total_cost'], 1800.0)
        self.assertEqual(payload['by_environment'][0]['environment'], 'prod')
        self.assertTrue(
            any(point['period'] == self.current_month for point in payload['cost_trend'])
        )

    def test_cost_report_supports_historical_months_without_resync(self):
        response = self.client.get('/api/cmdb/cost/report/', {'month': self.previous_month})

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['total_monthly_cost'], 1000.0)
        self.assertEqual(len(payload['top_cost_items']), 1)
        self.assertEqual(payload['top_cost_items'][0]['name'], 'prod-db-01')

    def test_optimization_returns_actionable_suggestions(self):
        response = self.client.get(
            '/api/cmdb/optimization/suggestions/',
            {'month': self.current_month},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['month'], self.current_month)
        self.assertGreaterEqual(payload['suggestion_count'], 3)
        self.assertGreater(payload['total_potential_saving'], 0)
        titles = [item['title'] for item in payload['suggestions']]
        self.assertTrue(any('prod-db-01' in title for title in titles))
        self.assertTrue(any('test-host-01' in title for title in titles))
        self.assertTrue(any('idle-host-01' in title for title in titles))


class CmdbTopologyTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        app_type = CIType.objects.create(name='Application')
        host_type = CIType.objects.create(name='Host')

        self.core_prod = ConfigItem.objects.create(
            name='core-app-prod',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.0.10', 'monthly_cost': 500},
        )
        self.core_db = ConfigItem.objects.create(
            name='core-db-prod',
            ci_type=host_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.0.11', 'monthly_cost': 800},
        )
        self.shared_cache = ConfigItem.objects.create(
            name='shared-cache-prod',
            ci_type=host_type,
            business_line='shared',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.1.10', 'monthly_cost': 300},
        )
        CIRelation.objects.create(
            source=self.core_prod,
            target=self.core_db,
            relation_type='depends_on',
            description='Primary dependency',
        )
        CIRelation.objects.create(
            source=self.core_prod,
            target=self.shared_cache,
            relation_type='connects_to',
            description='Cross business dependency',
        )

    def test_topology_scope_neighbors_keeps_cross_scope_neighbors(self):
        response = self.client.get(
            '/api/cmdb/topology/data/',
            {
                'business_line': 'core',
                'environment': 'prod',
                'scope': 'neighbors',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        node_names = {node['name'] for node in payload['nodes']}
        self.assertEqual(payload['meta']['scope'], 'neighbors')
        self.assertIn('core-app-prod', node_names)
        self.assertIn('core-db-prod', node_names)
        self.assertIn('shared-cache-prod', node_names)
        self.assertEqual(len(payload['meta']['matched_node_ids']), 2)
        self.assertTrue(any(edge['target_name'] == 'shared-cache-prod' for edge in payload['edges']))
        self.assertTrue(any(edge['label'] == '连接到' for edge in payload['edges']))

    def test_topology_scope_exact_only_returns_matching_nodes(self):
        response = self.client.get(
            '/api/cmdb/topology/data/',
            {
                'business_line': 'core',
                'environment': 'prod',
                'scope': 'exact',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        node_names = {node['name'] for node in payload['nodes']}
        self.assertEqual(payload['meta']['scope'], 'exact')
        self.assertEqual(node_names, {'core-app-prod', 'core-db-prod'})
        self.assertFalse(any(edge['target_name'] == 'shared-cache-prod' for edge in payload['edges']))


class CmdbRelationValidationTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        app_type = CIType.objects.create(name='Application')
        self.app_a = ConfigItem.objects.create(
            name='app-a',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
        )
        self.app_b = ConfigItem.objects.create(
            name='app-b',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
        )

    def test_relation_api_rejects_self_reference(self):
        response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_a.id,
                'relation_type': 'depends_on',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CIRelation.objects.count(), 0)

    def test_relation_api_rejects_duplicate_relation(self):
        response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_b.id,
                'relation_type': 'depends_on',
            },
        )
        self.assertEqual(response.status_code, 201)

        duplicate_response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_b.id,
                'relation_type': 'depends_on',
            },
        )

        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(CIRelation.objects.count(), 1)
