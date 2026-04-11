from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from ops.models import Alert, Host
from rbac.models import Role
from rbac.services import ensure_builtin_rbac

from .models import AIOpsChatMessage, AIOpsChatSession, AIOpsMCPServer, AIOpsModelProvider
from .services import _request_model_completion, get_agent_config, query_alerts, query_recent_changes


User = get_user_model()


class AIOpsApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = User.objects.create_user(username='aiops_user', password='Passw0rd!123')
        platform_admin = Role.objects.get(code='platform-admin')
        self.user.rbac_roles.add(platform_admin)
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        Host.objects.create(hostname='prod-web-01', ip_address='10.0.0.10', environment='prod', status='online')

    def test_bootstrap_returns_runtime(self):
        response = self.client.get('/api/aiops/bootstrap/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertTrue(response.data['active_mcp_servers'])
        self.assertTrue(response.data['active_skills'])
        active_mcp_names = {item['name'] for item in response.data['active_mcp_servers']}
        self.assertTrue({
            'CMDB MCP',
            '可观测性 MCP',
            '工单系统 MCP',
            '任务中心 MCP',
            '事件墙 MCP',
            '容器管理 MCP',
            '中间件 MCP',
            'SkyWalking MCP',
            'Grafana MCP',
        }.issubset(active_mcp_names))
        self.assertTrue(any(item['name'] == 'N9E 监控 MCP' for item in response.data['active_mcp_servers']))

    def test_get_agent_config_creates_n9e_mcp_preset(self):
        get_agent_config()
        server = AIOpsMCPServer.objects.get(name='N9E 监控 MCP')
        self.assertEqual(server.server_type, AIOpsMCPServer.SERVER_STDIO)
        self.assertIn('@n9e/n9e-mcp-server', server.endpoint_or_command)
        self.assertTrue(server.is_builtin)

    def test_get_agent_config_creates_default_experience_provider(self):
        config = get_agent_config()
        provider = AIOpsModelProvider.objects.get(name='智能助手体验版')
        self.assertEqual(provider.provider_type, AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE)
        self.assertEqual(provider.default_model, 'gpt-4o-mini')
        self.assertTrue(provider.has_api_key)
        self.assertEqual(config.default_provider_id, provider.id)

    def test_get_agent_config_keeps_existing_default_provider(self):
        custom_provider = AIOpsModelProvider.objects.create(
            name='custom-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://real.example.com/v1',
            default_model='real-model',
            is_enabled=True,
        )
        custom_provider.set_api_key('real-key')
        custom_provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = custom_provider
        config.save(update_fields=['default_provider'])

        refreshed = get_agent_config()
        self.assertEqual(refreshed.default_provider_id, custom_provider.id)

    def test_get_agent_config_keeps_user_edited_experience_provider(self):
        config = get_agent_config()
        provider = AIOpsModelProvider.objects.get(name='智能助手体验版')
        provider.base_url = 'https://custom-openai.example.com/v1'
        provider.default_model = 'custom-model'
        provider.save(update_fields=['base_url', 'default_model'])

        get_agent_config()
        provider.refresh_from_db()
        self.assertEqual(provider.base_url, 'https://custom-openai.example.com/v1')
        self.assertEqual(provider.default_model, 'custom-model')

    def test_mcp_and_skill_list_endpoints_bootstrap_builtin_assets(self):
        mcp_response = self.client.get('/api/aiops/admin/mcp-servers/')
        skill_response = self.client.get('/api/aiops/admin/skills/')
        self.assertEqual(mcp_response.status_code, 200)
        self.assertEqual(skill_response.status_code, 200)
        self.assertTrue(any(item['name'] == 'CMDB MCP' and item['server_type'] == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'N9E 监控 MCP' for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'SkyWalking MCP' and item['server_type'] == AIOpsMCPServer.SERVER_STDIO for item in mcp_response.data))
        self.assertTrue(any(item['name'] == 'Grafana MCP' and item['server_type'] == AIOpsMCPServer.SERVER_HTTP for item in mcp_response.data))
        self.assertTrue(any(item['slug'] == 'evidence-first-responder' for item in skill_response.data))

    @mock.patch('aiops.views.test_model_provider_connection')
    def test_provider_test_connection_endpoint_uses_real_check(self, mocked_test_connection):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-check',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        mocked_test_connection.return_value = {'status': 'success', 'message': '模型连接成功（实际调用模型：gpt-5.2-low）'}

        response = self.client.post(f'/api/aiops/admin/providers/{provider.id}/test_connection/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('gpt-5.2-low', response.data['message'])

    @mock.patch('aiops.services.requests.post')
    def test_request_model_completion_falls_back_to_low_variant(self, mocked_post):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-fallback',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='gpt-5.2',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        empty_response = mock.Mock()
        empty_response.status_code = 200
        empty_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': None}}],
        }
        low_response = mock.Mock()
        low_response.status_code = 200
        low_response.json.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': '连接成功'}}],
        }
        mocked_post.side_effect = [empty_response, low_response]

        result = _request_model_completion(provider, {
            'model': 'gpt-5.2',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 16,
        })
        self.assertEqual(result['choices'][0]['message']['content'], '连接成功')
        self.assertEqual(result['_meta']['resolved_model'], 'gpt-5.2-low')

    def test_query_recent_changes_does_not_use_missing_updated_at_field(self):
        session = AIOpsChatSession.objects.create(user=self.user, title='changes-check')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='最近发版')
        result = query_recent_changes(session, user_message, self.user, limit=5)
        self.assertNotIn('error', result)
        self.assertIn('sections', result)

    def test_query_alerts_handles_generic_chinese_alert_question(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='Disk usage warning',
            level='warning',
            source='monitor',
            message='disk > 80%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-check')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        result = query_alerts(session, user_message, self.user, query='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f', level='critical', only_unacknowledged=True)
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertEqual(result['alerts'][0].level, 'critical')

    def test_query_alerts_infers_filters_from_natural_language_query(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='Disk usage warning',
            level='warning',
            source='monitor',
            message='disk > 80%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-infer')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        result = query_alerts(session, user_message, self.user, query='\u5f53\u524d\u672a\u786e\u8ba4\u7684\u4e25\u91cd\u544a\u8b66\u6709\u54ea\u4e9b\uff1f')
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertEqual(result['alerts'][0].level, 'critical')

    def test_query_alerts_infers_filters_from_model_style_expression(self):
        Alert.objects.create(
            title='CPU usage high',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=False,
            host=Host.objects.first(),
        )
        Alert.objects.create(
            title='CPU usage high acknowledged',
            level='critical',
            source='monitor',
            message='cpu > 95%',
            is_acknowledged=True,
            host=Host.objects.first(),
        )
        session = AIOpsChatSession.objects.create(user=self.user, title='alert-expression')
        user_message = AIOpsChatMessage.objects.create(session=session, role='user', content='type:alert severity:critical acknowledged:false status:active')
        result = query_alerts(session, user_message, self.user, query='type:alert severity:critical acknowledged:false status:active')
        self.assertEqual(result['summary']['count'], 1)
        self.assertEqual(result['summary']['critical'], 1)
        self.assertFalse(result['alerts'][0].is_acknowledged)

    def test_send_message_creates_session_messages(self):
        session_response = self.client.post('/api/aiops/sessions/', {'title': '测试会话'}, format='json')
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生产环境有哪些主机？'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIOpsChatSession.objects.get(pk=session_id).messages.count(), 2)

    def test_send_message_returns_error_when_no_model_available(self):
        get_agent_config()
        AIOpsModelProvider.objects.all().update(is_enabled=False)
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'no-model'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '?????????'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['assistant_message']['message_type'], AIOpsChatMessage.TYPE_ERROR)
        self.assertEqual(response.data['assistant_message']['metadata']['error_code'], 'provider_unavailable')

    @mock.patch('aiops.views.start_async_chat_processing')
    def test_send_message_async_returns_placeholder_assistant(self, mocked_start_async):
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'async-chat'}, format='json')
        self.assertEqual(session_response.status_code, 201)
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message_async/',
            {'content': 'async alert question'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIOpsChatSession.objects.get(pk=session_id).messages.count(), 2)
        self.assertEqual(response.data['assistant_message']['metadata']['processing_status'], 'pending')
        mocked_start_async.assert_called_once()

    @mock.patch('aiops.services._request_model_completion')
    def test_task_request_creates_pending_action(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-task-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])
        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_task_1',
                            'type': 'function',
                            'function': {
                                'name': 'generate_host_task',
                                'arguments': '{"request_summary":"???? Redis ????","task_kind":"service_status","service_name":"redis","environment":"prod"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '???????????????',
                    },
                }],
            },
        ]
        session_response = self.client.post('/api/aiops/sessions/', {'title': '??????'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '???????Redis ??????'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.data['pending_action'])
    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_returns_error_when_model_does_not_call_tools(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-no-tool-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])
        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])
        mocked_completion.return_value = {
            'choices': [{
                'message': {
                    'content': '????????????????',
                },
            }],
        }
        session_response = self.client.post('/api/aiops/sessions/', {'title': 'no-tool-call'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '?????????'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['assistant_message']['message_type'], AIOpsChatMessage.TYPE_ERROR)
        self.assertEqual(response.data['assistant_message']['metadata']['error_code'], 'no_tool_called')


    def test_task_request_respects_action_execution_switch(self):
        config = get_agent_config()
        config.allow_action_execution = False
        config.save(update_fields=['allow_action_execution'])
        session_response = self.client.post('/api/aiops/sessions/', {'title': '任务会话'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '生成一份 Redis 巡检任务'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['pending_action'])

    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_uses_llm_tool_calling_runtime(self, mocked_completion):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        config = get_agent_config()
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_1',
                            'type': 'function',
                            'function': {
                                'name': 'query_cmdb_items',
                                'arguments': '{"query":"生产 主机"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '已通过 MCP 查询到平台资源，并整理出主机结果。',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'tool-calling'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '请帮我看下生产环境 CMDB 资源'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('query_cmdb_items', response.data['assistant_message']['tool_calls'])

    @mock.patch('aiops.views.test_mcp_server_connection')
    def test_mcp_test_connection_endpoint(self, mocked_test_connection):
        server = AIOpsMCPServer.objects.create(
            name='HTTP MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            is_enabled=True,
        )
        mocked_test_connection.return_value = {'status': 'success', 'message': 'ok'}
        response = self.client.post(f'/api/aiops/admin/mcp-servers/{server.id}/test_connection/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')

    @mock.patch('aiops.views.list_mcp_server_tools')
    def test_mcp_list_tools_endpoint(self, mocked_list_tools):
        server = AIOpsMCPServer.objects.create(
            name='HTTP MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            is_enabled=True,
        )
        mocked_list_tools.return_value = {'count': 1, 'tools': [{'name': 'status'}]}
        response = self.client.get(f'/api/aiops/admin/mcp-servers/{server.id}/list_tools/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    @mock.patch('aiops.services._create_mcp_client_session')
    @mock.patch('aiops.services._request_model_completion')
    def test_send_message_uses_external_mcp_tool(self, mocked_completion, mocked_create_session):
        provider = AIOpsModelProvider.objects.create(
            name='mock-provider-external',
            provider_type=AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
            base_url='https://example.com/v1',
            default_model='mock-model',
            is_enabled=True,
        )
        provider.set_api_key('test-key')
        provider.save(update_fields=['api_key_encrypted'])

        mcp_server = AIOpsMCPServer.objects.create(
            name='External Ops MCP',
            server_type=AIOpsMCPServer.SERVER_HTTP,
            endpoint_or_command='https://mcp.example.com',
            tool_whitelist=['server_status'],
            is_enabled=True,
        )

        config = get_agent_config()
        config.default_provider = provider
        config.enabled_mcp_server_ids = list(dict.fromkeys([*(config.enabled_mcp_server_ids or []), mcp_server.id]))
        config.save(update_fields=['default_provider', 'enabled_mcp_server_ids'])

        fake_session = mock.Mock()
        fake_session.list_tools.return_value = [
            {
                'name': 'server_status',
                'description': '返回外部系统状态',
                'inputSchema': {'type': 'object', 'properties': {'service': {'type': 'string'}}},
            },
        ]
        fake_session.call_tool.return_value = {
            'content': [{'type': 'text', 'text': 'external-ok'}],
            'structuredContent': {'status': 'ok'},
        }
        mocked_create_session.return_value = fake_session
        mocked_completion.side_effect = [
            {
                'choices': [{
                    'message': {
                        'tool_calls': [{
                            'id': 'call_external',
                            'type': 'function',
                            'function': {
                                'name': 'mcp__External_Ops_MCP__server_status',
                                'arguments': '{"service":"gateway"}',
                            },
                        }],
                    },
                }],
            },
            {
                'choices': [{
                    'message': {
                        'content': '已通过外部 MCP 工具获取 gateway 状态。',
                    },
                }],
            },
        ]

        session_response = self.client.post('/api/aiops/sessions/', {'title': 'external-mcp'}, format='json')
        session_id = session_response.data['id']
        response = self.client.post(
            f'/api/aiops/sessions/{session_id}/send_message/',
            {'content': '查询 gateway 的外部状态'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('mcp__External_Ops_MCP__server_status', response.data['assistant_message']['tool_calls'])
        self.assertGreaterEqual(fake_session.initialize.call_count, 1)
        fake_session.call_tool.assert_called_once_with('server_status', {'service': 'gateway'})
