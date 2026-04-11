import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
import uuid
from collections import Counter
from decimal import Decimal

import requests
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from cmdb.models import ConfigItem
from eventwall.models import EventRecord
from eventwall.services import record_event
from iac.models import TerraformExecution, TerraformStack
from multicloud.models import CloudAsset
from ops.host_tasks import start_host_task
from ops.models import (
    Alert,
    Deployment,
    DockerHost,
    Host,
    HostTask,
    K8sCluster,
    LogDataSource,
    LogEntry,
    NginxEnvironment,
    TransactionTicket,
)
from ops.observability_views import DEMO_TRACES
from ops.middleware_views import _build_payload as build_middleware_payload
from ops.middleware_views import _get_demo_state as get_middleware_demo_state
from rbac.services import user_has_permissions

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsSkill,
    AIOpsToolInvocation,
)


DEFAULT_SUGGESTED_QUESTIONS = [
    '当前未确认的严重告警有哪些？',
    '生产环境有哪些离线主机？',
    '分析 payment-service 最近异常。',
    '生成一份 Redis 巡检任务。',
]

DEFAULT_SYSTEM_PROMPT = (
    '你是 SxDevOps 平台内的 AIOps 智能助手。'
    '必须优先通过可用的 MCP 工具获取平台内结构化数据，严禁编造不存在的资源、告警、日志、链路和执行结果。'
    '回答时区分事实、推断和建议；涉及执行类动作时，未确认前只能生成草稿。'
)

STOPWORDS = {
    '帮我', '一下', '当前', '最近', '平台', '资源', '信息', '告警', '分析', '排查', '问题',
    '哪些', '多少', '怎么', '情况', '查看', '查询', '生成', '执行', '触发', '自动', '任务', '中心',
}

ALERT_QUERY_NOISE_PATTERNS = [
    '\u5f53\u524d', '\u76ee\u524d', '\u6700\u8fd1', '\u6709\u54ea\u4e9b', '\u6709\u4ec0\u4e48', '\u54ea\u4e9b', '\u4ec0\u4e48', '\u544a\u8b66\u4e2d\u5fc3',
    '\u544a\u8b66', '\u4e25\u91cd', '\u9ad8\u5371', '\u8b66\u544a', '\u4fe1\u606f', '\u672a\u786e\u8ba4', '\u5df2\u786e\u8ba4', '\u786e\u8ba4',
    '\u72b6\u6001', '\u67e5\u770b', '\u67e5\u8be2', '\u5217\u51fa', '\u5e2e\u6211', '\u770b\u4e0b', '\u4e00\u4e0b', '\u5168\u90e8', '\u6240\u6709',
]

DANGEROUS_COMMAND_PATTERNS = [
    'rm -rf',
    'shutdown',
    'reboot',
    'mkfs',
    'userdel',
    'kill -9',
]

MCP_PROTOCOL_VERSION = '2025-03-26'
MCP_CLIENT_INFO = {'name': 'SxDevOps AIOps', 'version': '1.0.0'}

PROCESSING_STATUS_PENDING = 'pending'
PROCESSING_STATUS_RUNNING = 'running'
PROCESSING_STATUS_STREAMING = 'streaming'
PROCESSING_STATUS_COMPLETED = 'completed'
PROCESSING_STATUS_FAILED = 'failed'

BUILTIN_MCP_SERVERS = [
    {
        'name': 'CMDB MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 CMDB 配置项与资源关系。',
        'tool_whitelist': ['query_cmdb_items'],
    },
    {
        'name': '可观测性 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询告警、日志、链路与最近变更。',
        'tool_whitelist': ['query_observability'],
    },
    {
        'name': '工单系统 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询事务工单与当前处理状态。',
        'tool_whitelist': ['query_workorders'],
    },
    {
        'name': '任务中心 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询主机任务并生成任务草稿。',
        'tool_whitelist': ['query_task_center', 'generate_host_task'],
    },
    {
        'name': '事件墙 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询事件墙中的关键事件与最近动态。',
        'tool_whitelist': ['query_event_wall'],
    },
    {
        'name': '容器管理 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 Kubernetes 集群与 Docker 主机。',
        'tool_whitelist': ['query_container_assets'],
    },
    {
        'name': '中间件 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 Nginx、Redis、RocketMQ、Elasticsearch 等中间件状态。',
        'tool_whitelist': ['query_middleware_assets'],
    },
    {
        'name': 'N9E 监控 MCP',
        'server_type': AIOpsMCPServer.SERVER_STDIO,
        'description': '对接 Nightingale（N9E）官方 MCP Server，查询告警、监控目标、数据源、事件流水线与团队信息。',
        'endpoint_or_command': 'npx -y @n9e/n9e-mcp-server stdio',
        'auth_config': {
            'timeout_seconds': 20,
            'env': {
                'N9E_TOKEN': 'demo-n9e-token',
                'N9E_BASE_URL': 'http://nightingale.example.com:17000',
                'N9E_READ_ONLY': 'true',
                'N9E_TOOLSETS': 'alerts,targets,datasource,mutes,busi_groups,notify_rules,alert_subscribes,event_pipelines,users',
            },
        },
        'tool_whitelist': [
            'list_active_alerts',
            'get_active_alert',
            'list_history_alerts',
            'get_history_alert',
            'list_alert_rules',
            'get_alert_rule',
            'list_targets',
            'list_datasources',
            'list_mutes',
            'get_mute',
            'create_mute',
            'update_mute',
            'list_notify_rules',
            'get_notify_rule',
            'list_alert_subscribes',
            'list_alert_subscribes_by_gids',
            'get_alert_subscribe',
            'list_event_pipelines',
            'get_event_pipeline',
            'list_event_pipeline_executions',
            'list_all_event_pipeline_executions',
            'get_event_pipeline_execution',
            'list_users',
            'get_user',
            'list_user_groups',
            'get_user_group',
            'list_busi_groups',
        ],
    },
    {
        'name': 'SkyWalking MCP',
        'server_type': AIOpsMCPServer.SERVER_STDIO,
        'description': '对接 Apache SkyWalking 官方 MCP Server，查询 APM、拓扑、链路与相关可观测性数据。',
        'endpoint_or_command': 'swmcp stdio --read-only --sw-url http://skywalking-oap.example.com:12800 --sw-username ${SW_USERNAME} --sw-password ${SW_PASSWORD}',
        'auth_config': {
            'timeout_seconds': 20,
            'env': {
                'SW_USERNAME': 'demo-skywalking-admin',
                'SW_PASSWORD': 'demo-skywalking-password',
                'SKYWALKING_OAP_URL': 'http://skywalking-oap.example.com:12800',
            },
        },
        'tool_whitelist': [
            'query_traces',
            'query_logs',
            'execute_mqe_expression',
            'list_mqe_metrics',
            'get_mqe_metric_type',
            'list_layers',
            'list_services',
            'list_instances',
            'list_endpoints',
            'list_processes',
        ],
    },
    {
        'name': 'Grafana MCP',
        'server_type': AIOpsMCPServer.SERVER_HTTP,
        'description': '对接 Grafana MCP Server，通过 HTTP 方式查询仪表盘、数据源、Prometheus 与 Loki 等能力。',
        'endpoint_or_command': 'http://grafana-mcp.example.com/mcp',
        'auth_config': {
            'timeout_seconds': 20,
            'headers': {
                'Authorization': 'Bearer demo-grafana-service-account-token',
                'X-Grafana-URL': 'http://grafana.example.com',
            },
            'grafana_url': 'http://grafana.example.com',
            'service_account_token': 'demo-grafana-service-account-token',
        },
        'tool_whitelist': [
            'search_dashboards',
            'get_dashboard_by_uid',
            'get_dashboard_summary',
            'get_dashboard_property',
            'get_dashboard_panel_queries',
            'list_datasources',
            'get_datasource',
            'query_prometheus',
            'query_loki_logs',
            'list_incidents',
        ],
    },
]

BUILTIN_SKILLS = [
    {
        'name': '证据优先应答',
        'slug': 'evidence-first-responder',
        'description': '优先调用工具取证，再输出事实、推断与建议。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '先调用 MCP 工具获取平台事实，再作答。输出结构优先为：事实、推断、建议。',
        'allowed_role_codes': [],
    },
    {
        'name': '故障关联分析',
        'slug': 'incident-investigator',
        'description': '围绕告警、事件、日志、链路和变更做关联分析。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '异常、故障、根因类问题优先组合调用告警、事件、日志、链路和最近变更工具。',
        'allowed_role_codes': [],
    },
    {
        'name': '自动化安全护栏',
        'slug': 'automation-safety-guard',
        'description': '执行类任务先生成草稿，强调范围、风险与确认。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '涉及任务执行时，先生成草稿，列出目标、执行方式、执行策略与风险等级，未确认前不能声称已执行。',
        'allowed_role_codes': [],
    },
]

BUILTIN_MODEL_PROVIDER = {
    'name': '智能助手体验版',
    'provider_type': AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
    'base_url': 'https://api.openai.example.com/v1',
    'default_model': 'gpt-4o-mini',
    'backup_model': 'gpt-4.1-mini',
    'temperature': 0.2,
    'max_tokens': 1600,
    'timeout_seconds': 30,
    'api_key': 'demo-openai-compatible-key',
    'last_test_message': '预置体验配置，需替换为真实 API Key 后使用',
}


def _normalize_json_id_list(values):
    normalized = []
    for value in values or []:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def _ensure_builtin_runtime_assets(config):
    builtin_mcp_ids = []
    builtin_skill_ids = []
    builtin_mcp_names = {item['name'] for item in BUILTIN_MCP_SERVERS}
    builtin_skill_slugs = {item['slug'] for item in BUILTIN_SKILLS}

    for definition in BUILTIN_MCP_SERVERS:
        server, _ = AIOpsMCPServer.objects.get_or_create(
            name=definition['name'],
            defaults={
                'server_type': definition['server_type'],
                'description': definition['description'],
                'endpoint_or_command': definition.get('endpoint_or_command', ''),
                'auth_config': definition.get('auth_config', {}),
                'tool_whitelist': definition['tool_whitelist'],
                'is_builtin': True,
                'is_enabled': True,
            },
        )
        changed_fields = []
        if not server.is_builtin:
            server.is_builtin = True
            changed_fields.append('is_builtin')
        if server.server_type != definition['server_type']:
            server.server_type = definition['server_type']
            changed_fields.append('server_type')
        if server.tool_whitelist != definition['tool_whitelist']:
            server.tool_whitelist = definition['tool_whitelist']
            changed_fields.append('tool_whitelist')
        if server.description != definition['description']:
            server.description = definition['description']
            changed_fields.append('description')
        if definition.get('endpoint_or_command') and not server.endpoint_or_command:
            server.endpoint_or_command = definition['endpoint_or_command']
            changed_fields.append('endpoint_or_command')
        if definition.get('auth_config') and not server.auth_config:
            server.auth_config = definition['auth_config']
            changed_fields.append('auth_config')
        if changed_fields:
            server.save(update_fields=changed_fields)
        builtin_mcp_ids.append(server.id)

    AIOpsMCPServer.objects.filter(is_builtin=True).exclude(name__in=builtin_mcp_names).delete()

    for definition in BUILTIN_SKILLS:
        skill, _ = AIOpsSkill.objects.get_or_create(
            slug=definition['slug'],
            defaults={
                'name': definition['name'],
                'description': definition['description'],
                'source_type': definition['source_type'],
                'content': definition['content'],
                'allowed_role_codes': definition['allowed_role_codes'],
                'is_builtin': True,
                'is_enabled': True,
            },
        )
        changed_fields = []
        if not skill.is_builtin:
            skill.is_builtin = True
            changed_fields.append('is_builtin')
        if skill.name != definition['name']:
            skill.name = definition['name']
            changed_fields.append('name')
        if skill.source_type != definition['source_type']:
            skill.source_type = definition['source_type']
            changed_fields.append('source_type')
        if not skill.content:
            skill.content = definition['content']
            changed_fields.append('content')
        if not skill.description:
            skill.description = definition['description']
            changed_fields.append('description')
        if changed_fields:
            skill.save(update_fields=changed_fields)
        builtin_skill_ids.append(skill.id)

    AIOpsSkill.objects.filter(is_builtin=True).exclude(slug__in=builtin_skill_slugs).delete()

    update_fields = []
    valid_mcp_ids = set(AIOpsMCPServer.objects.values_list('id', flat=True))
    valid_skill_ids = set(AIOpsSkill.objects.values_list('id', flat=True))
    current_mcp_ids = [item for item in _normalize_json_id_list(config.enabled_mcp_server_ids) if item in valid_mcp_ids and item not in builtin_mcp_ids]
    current_skill_ids = [item for item in _normalize_json_id_list(config.enabled_skill_ids) if item in valid_skill_ids and item not in builtin_skill_ids]
    next_mcp_ids = list(dict.fromkeys([*builtin_mcp_ids, *current_mcp_ids]))
    next_skill_ids = list(dict.fromkeys([*builtin_skill_ids, *current_skill_ids]))
    if next_mcp_ids != (config.enabled_mcp_server_ids or []):
        config.enabled_mcp_server_ids = next_mcp_ids
        update_fields.append('enabled_mcp_server_ids')
    if next_skill_ids != (config.enabled_skill_ids or []):
        config.enabled_skill_ids = next_skill_ids
        update_fields.append('enabled_skill_ids')
    if update_fields:
        config.save(update_fields=update_fields)


def _ensure_builtin_model_provider(config):
    definition = BUILTIN_MODEL_PROVIDER
    provider, created = AIOpsModelProvider.objects.get_or_create(
        name=definition['name'],
        defaults={
            'provider_type': definition['provider_type'],
            'base_url': definition['base_url'],
            'default_model': definition['default_model'],
            'backup_model': definition['backup_model'],
            'temperature': definition['temperature'],
            'max_tokens': definition['max_tokens'],
            'timeout_seconds': definition['timeout_seconds'],
            'is_enabled': True,
            'last_test_status': AIOpsModelProvider.STATUS_UNKNOWN,
            'last_test_message': definition['last_test_message'],
        },
    )
    changed_fields = []
    for field in ['provider_type', 'base_url', 'default_model', 'backup_model']:
        if not getattr(provider, field):
            setattr(provider, field, definition[field])
            changed_fields.append(field)
    for field in ['temperature', 'max_tokens', 'timeout_seconds']:
        if not getattr(provider, field):
            setattr(provider, field, definition[field])
            changed_fields.append(field)
    if created and not provider.is_enabled:
        provider.is_enabled = True
        changed_fields.append('is_enabled')
    if not provider.last_test_message:
        provider.last_test_message = definition['last_test_message']
        changed_fields.append('last_test_message')
    if created or not provider.has_api_key:
        provider.set_api_key(definition['api_key'])
        changed_fields.append('api_key_encrypted')
    if changed_fields:
        provider.save(update_fields=list(dict.fromkeys(changed_fields)))

    if not config.default_provider_id:
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

    return provider


def get_agent_config():
    config, _ = AIOpsAgentConfig.objects.get_or_create(
        name='default',
        defaults={
            'suggested_questions': DEFAULT_SUGGESTED_QUESTIONS,
            'system_prompt': DEFAULT_SYSTEM_PROMPT,
        },
    )
    update_fields = []
    if not config.suggested_questions:
        config.suggested_questions = DEFAULT_SUGGESTED_QUESTIONS
        update_fields.append('suggested_questions')
    if not config.system_prompt:
        config.system_prompt = DEFAULT_SYSTEM_PROMPT
        update_fields.append('system_prompt')
    if update_fields:
        config.save(update_fields=update_fields)
    _ensure_builtin_runtime_assets(config)
    _ensure_builtin_model_provider(config)
    return config


def get_active_provider(config=None):
    config = config or get_agent_config()
    provider = config.default_provider
    if provider and provider.is_enabled:
        return provider
    return AIOpsModelProvider.objects.filter(is_enabled=True).order_by('id').first()


def _get_selected_mcp_servers(config):
    selected_ids = _normalize_json_id_list(config.enabled_mcp_server_ids)
    queryset = AIOpsMCPServer.objects.filter(is_enabled=True)
    if selected_ids:
        queryset = queryset.filter(id__in=selected_ids)
    return list(queryset.order_by('is_builtin', 'id'))


def _get_selected_skills(config, user=None):
    selected_ids = _normalize_json_id_list(config.enabled_skill_ids)
    queryset = AIOpsSkill.objects.filter(is_enabled=True)
    if selected_ids:
        queryset = queryset.filter(id__in=selected_ids)
    skills = list(queryset.order_by('is_builtin', 'name', 'id'))
    if not user:
        return skills
    role_codes = set(user.rbac_roles.values_list('code', flat=True))
    filtered = []
    for skill in skills:
        allowed_codes = set(skill.allowed_role_codes or [])
        if allowed_codes and not (allowed_codes & role_codes):
            continue
        filtered.append(skill)
    return filtered


def bootstrap_payload_for_user(user):
    config = get_agent_config()
    provider = get_active_provider(config)
    selected_mcp_servers = _get_selected_mcp_servers(config)
    selected_skills = _get_selected_skills(config, user=user)
    return {
        'enabled': config.is_enabled and user_has_permissions(user, ['aiops.chat.view']),
        'welcome_message': config.welcome_message,
        'suggested_questions': config.suggested_questions or DEFAULT_SUGGESTED_QUESTIONS,
        'permissions': {
            'chat': user_has_permissions(user, ['aiops.chat.view']),
            'analyze': user_has_permissions(user, ['aiops.chat.analyze']),
            'generate_task': user_has_permissions(user, ['aiops.task.generate']),
            'execute_task': user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']),
            'config_view': user_has_permissions(user, ['aiops.config.view']),
            'config_manage': user_has_permissions(user, ['aiops.config.manage']),
        },
        'provider': {
            'name': provider.name if provider else '未配置模型',
            'model': provider.default_model if provider else '',
        },
        'runtime': {
            'allow_action_execution': config.allow_action_execution,
            'require_confirmation': config.require_confirmation,
            'show_evidence': config.show_evidence,
            'allow_analysis': config.allow_analysis,
        },
        'active_mcp_servers': [
            {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'tool_whitelist': item.tool_whitelist,
                'is_builtin': item.is_builtin,
            }
            for item in selected_mcp_servers
        ],
        'active_skills': [
            {
                'id': item.id,
                'name': item.name,
                'slug': item.slug,
                'description': item.description,
                'is_builtin': item.is_builtin,
            }
            for item in selected_skills
        ],
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _clean_tokens(text):
    chunks = re.split(r'[\s,，。！？；:：/\\|()\[\]{}]+', text or '')
    tokens = []
    for chunk in chunks:
        token = chunk.strip().strip('"\'')
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens[:8]


def _clean_alert_query_tokens(text):
    cleaned = text or ''
    for pattern in ALERT_QUERY_NOISE_PATTERNS:
        if pattern:
            cleaned = cleaned.replace(pattern, ' ')
    tokens = _clean_tokens(cleaned)
    deduped = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:8]


def _normalize_alert_query_request(query='', level='', only_unacknowledged=False):
    raw_query = query or ''
    normalized_query = raw_query
    resolved_level = (level or '').strip().lower()
    resolved_unacknowledged = bool(only_unacknowledged)

    level_match = re.search(r'\b(?:severity|level)\s*[:=]\s*(critical|warning|info)\b', raw_query, re.IGNORECASE)
    if not resolved_level and level_match:
        resolved_level = level_match.group(1).lower()
    if not resolved_level:
        if '严重' in raw_query or '高危' in raw_query:
            resolved_level = 'critical'
        elif '警告' in raw_query:
            resolved_level = 'warning'
        elif '信息' in raw_query:
            resolved_level = 'info'

    acknowledged_match = re.search(
        r'\b(?:acknowledged|is_acknowledged)\s*[:=]\s*(true|false|1|0|yes|no)\b',
        raw_query,
        re.IGNORECASE,
    )
    if not resolved_unacknowledged and acknowledged_match:
        resolved_unacknowledged = acknowledged_match.group(1).lower() in {'false', '0', 'no'}
    if not resolved_unacknowledged and any(keyword in raw_query for keyword in ['未确认', '未认领', '未处理']):
        resolved_unacknowledged = True

    filter_patterns = [
        r'\b(?:type|kind)\s*[:=]\s*alert\b',
        r'\b(?:severity|level)\s*[:=]\s*(?:critical|warning|info)\b',
        r'\b(?:acknowledged|is_acknowledged)\s*[:=]\s*(?:true|false|1|0|yes|no)\b',
        r'\bstatus\s*[:=]\s*(?:active|open|pending|closed)\b',
        r'\bAND\b',
    ]
    for pattern in filter_patterns:
        normalized_query = re.sub(pattern, ' ', normalized_query, flags=re.IGNORECASE)
    normalized_query = re.sub(r'\s+', ' ', normalized_query).strip()

    return normalized_query, resolved_level, resolved_unacknowledged


def _extract_environment(text):
    mapping = {'生产': 'prod', 'prod': 'prod', '测试': 'test', 'test': 'test', '开发': 'dev', 'dev': 'dev'}
    lowered = (text or '').lower()
    for keyword, code in mapping.items():
        if keyword in lowered:
            return code
    return ''


def _contains_any(text, keywords):
    lowered = (text or '').lower()
    return any(keyword in lowered for keyword in keywords)


def _is_unhelpful_answer(content):
    lowered = (content or '').strip().lower()
    if not lowered:
        return True
    patterns = [
        '我没看懂', '我不确定', '请补充', '请说明', '请澄清', '没理解',
        "i'm not sure", 'could you clarify', 'tell me what', 'need more context',
    ]
    return any(pattern in lowered for pattern in patterns)


def _queryset_search(queryset, fields, tokens):
    if not tokens:
        return queryset
    condition = Q()
    for token in tokens:
        token_condition = Q()
        for field in fields:
            token_condition |= Q(**{f'{field}__icontains': token})
        condition &= token_condition
    return queryset.filter(condition)


def _dedupe_citations(citations):
    deduped = []
    seen = set()
    for item in citations or []:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _create_tool_invocation(session, user_message, tool_name, request_payload):
    return AIOpsToolInvocation.objects.create(
        session=session,
        message=user_message,
        tool_name=tool_name,
        request_payload=request_payload,
    )


def _finish_tool_invocation(invocation, response_summary, started_at, success=True):
    invocation.status = AIOpsToolInvocation.STATUS_SUCCESS if success else AIOpsToolInvocation.STATUS_FAILED
    invocation.response_summary = response_summary
    invocation.latency_ms = max(int((time.time() - started_at) * 1000), 1)
    invocation.save(update_fields=['status', 'response_summary', 'latency_ms'])


def _append_limited_event(items, event, max_items=24):
    entries = list(items or [])
    entries.append(event)
    if len(entries) > max_items:
        entries = entries[-max_items:]
    return entries


def _update_chat_message_processing(
    message_id,
    *,
    status_value=None,
    text=None,
    step=None,
    tool_event=None,
    content=None,
    message_type=None,
    citations=None,
    tool_calls=None,
    metadata_updates=None,
):
    message = AIOpsChatMessage.objects.filter(pk=message_id).first()
    if not message:
        return None

    metadata = dict(message.metadata or {})
    changed_fields = []

    if status_value:
        metadata['processing_status'] = status_value
    if text is not None:
        metadata['processing_text'] = text
    if step:
        metadata['processing_steps'] = _append_limited_event(
            metadata.get('processing_steps'),
            {
                'title': step.get('title') or '',
                'detail': step.get('detail') or '',
                'status': step.get('status') or PROCESSING_STATUS_COMPLETED,
                'timestamp': timezone.now().isoformat(),
            },
            max_items=18,
        )
    if tool_event:
        metadata['tool_events'] = _append_limited_event(
            metadata.get('tool_events'),
            {
                'name': tool_event.get('name') or '',
                'detail': tool_event.get('detail') or '',
                'status': tool_event.get('status') or PROCESSING_STATUS_COMPLETED,
                'timestamp': timezone.now().isoformat(),
            },
            max_items=24,
        )
    if metadata_updates:
        metadata.update(metadata_updates)

    if message.metadata != metadata:
        message.metadata = metadata
        changed_fields.append('metadata')
    if content is not None and message.content != content:
        message.content = content
        changed_fields.append('content')
    if message_type and message.message_type != message_type:
        message.message_type = message_type
        changed_fields.append('message_type')
    if citations is not None and message.citations != citations:
        message.citations = citations
        changed_fields.append('citations')
    if tool_calls is not None and message.tool_calls != tool_calls:
        message.tool_calls = tool_calls
        changed_fields.append('tool_calls')

    if changed_fields:
        message.save(update_fields=changed_fields)
    return message


def _make_processing_callback(message_id):
    def emit(**kwargs):
        return _update_chat_message_processing(message_id, **kwargs)
    return emit


def _touch_chat_session(session, question=''):
    session.last_message_at = timezone.now()
    new_session_title = '\u65b0\u4f1a\u8bdd'
    if session.title == new_session_title:
        session.title = (question or new_session_title)[:48]
    session.save(update_fields=['last_message_at', 'title', 'updated_at'])


def _summarize_tool_result(tool_result):
    section_count = len(tool_result.get('sections') or [])
    citation_count = len(tool_result.get('citations') or [])
    if section_count and citation_count:
        return f'\u8fd4\u56de {section_count} \u4e2a\u7ed3\u679c\u5206\u7ec4\uff0c\u9644\u5e26 {citation_count} \u4e2a\u5f15\u7528\u3002'
    if section_count:
        return f'\u8fd4\u56de {section_count} \u4e2a\u7ed3\u679c\u5206\u7ec4\u3002'
    if citation_count:
        return f'\u8fd4\u56de {citation_count} \u4e2a\u5f15\u7528\u3002'
    tool_output = tool_result.get('tool_output') or {}
    if isinstance(tool_output, dict) and tool_output.get('error'):
        return str(tool_output.get('error'))
    return '\u8c03\u7528\u5b8c\u6210\u3002'


def query_resources(session, user_message, user, query='', environment='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    environment = environment or _extract_environment(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_resources',
        {'query': query, 'tokens': tokens, 'environment': environment, 'limit': limit},
    )
    sections = []
    citations = []
    summary = {}

    if user_has_permissions(user, ['ops.host.view']):
        host_queryset = Host.objects.all()
        if environment:
            host_queryset = host_queryset.filter(environment=environment)
        host_queryset = _queryset_search(host_queryset, ['hostname', 'ip_address', 'business_line', 'admin_user', 'description'], tokens)
        hosts = list(host_queryset.order_by('-updated_at')[:limit])
        if hosts:
            sections.append({
                'title': '主机资源',
                'items': [f'{host.hostname} ({host.ip_address}) / {host.get_status_display()}' for host in hosts],
            })
            summary['hosts'] = len(hosts)
            citations.append({'title': '主机中心', 'path': '/hosts/assets'})

    if user_has_permissions(user, ['cmdb.ci.view']):
        ci_queryset = ConfigItem.objects.select_related('ci_type').all()
        if environment:
            ci_queryset = ci_queryset.filter(environment=environment)
        ci_queryset = _queryset_search(ci_queryset, ['name', 'business_line', 'admin_user'], tokens)
        items = list(ci_queryset.order_by('-updated_at')[:limit])
        if items:
            sections.append({
                'title': 'CMDB 配置项',
                'items': [f'{item.name} / {item.ci_type.name} / {item.get_status_display()}' for item in items],
            })
            summary['cmdb_items'] = len(items)
            citations.append({'title': 'CMDB', 'path': '/cmdb', 'query': {'tab': 'items'}})

    if user_has_permissions(user, ['ops.multicloud.view']):
        asset_queryset = CloudAsset.objects.select_related('environment').all()
        asset_queryset = _queryset_search(asset_queryset, ['name', 'resource_id', 'resource_type', 'region', 'vpc_name'], tokens)
        assets = list(asset_queryset.order_by('-updated_at')[:limit])
        if assets:
            sections.append({
                'title': '多云资源',
                'items': [f'{asset.name} / {asset.resource_type} / {asset.get_status_display()}' for asset in assets],
            })
            summary['cloud_assets'] = len(assets)
            citations.append({'title': '多云环境', 'path': '/multicloud'})

    if user_has_permissions(user, ['ops.iac.view']):
        stack_queryset = _queryset_search(TerraformStack.objects.all(), ['name', 'description', 'region', 'zone'], tokens)
        stacks = list(stack_queryset.order_by('-updated_at')[:4])
        if stacks:
            sections.append({
                'title': 'IaC 方案',
                'items': [f'{stack.name} / {stack.get_cloud_provider_display()} / {stack.region}' for stack in stacks],
            })
            summary['iac_stacks'] = len(stacks)
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})

    if user_has_permissions(user, ['ops.k8s.view']):
        cluster_queryset = _queryset_search(K8sCluster.objects.all(), ['name', 'api_server', 'description'], tokens)
        clusters = list(cluster_queryset.order_by('-updated_at')[:5])
        if clusters:
            sections.append({
                'title': 'K8s 集群',
                'items': [f'{cluster.name} / {cluster.get_status_display()}' for cluster in clusters],
            })
            summary['k8s_clusters'] = len(clusters)
            citations.append({'title': 'K8s 集群', 'path': '/containers/k8s'})

    if user_has_permissions(user, ['ops.docker.view']):
        docker_queryset = _queryset_search(DockerHost.objects.all(), ['name', 'ip_address', 'description'], tokens)
        docker_hosts = list(docker_queryset.order_by('-updated_at')[:5])
        if docker_hosts:
            sections.append({
                'title': 'Docker 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in docker_hosts],
            })
            summary['docker_hosts'] = len(docker_hosts)
            citations.append({'title': 'Docker 环境', 'path': '/containers/docker'})

    if user_has_permissions(user, ['ops.nginx.view']):
        nginx_queryset = _queryset_search(NginxEnvironment.objects.all(), ['name', 'ip_address', 'description'], tokens)
        nginx_envs = list(nginx_queryset.order_by('-updated_at')[:5])
        if nginx_envs:
            sections.append({
                'title': 'Nginx 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in nginx_envs],
            })
            summary['nginx_envs'] = len(nginx_envs)
            citations.append({'title': 'Nginx 管理', 'path': '/middleware/nginx'})

    if user_has_permissions(user, ['ops.log.datasource.view']):
        datasource_queryset = _queryset_search(LogDataSource.objects.all(), ['name', 'provider', 'description'], tokens)
        datasources = list(datasource_queryset.order_by('-updated_at')[:5])
        if datasources:
            sections.append({
                'title': '日志数据源',
                'items': [f'{item.name} / {item.get_provider_display()} / {"启用" if item.is_enabled else "停用"}' for item in datasources],
            })
            summary['log_datasources'] = len(datasources)
            citations.append({'title': '日志数据源', 'path': '/logs/datasources'})

    response_summary = {'summary': summary, 'section_count': len(sections)}
    _finish_tool_invocation(invocation, response_summary, started_at, success=bool(sections))
    return {'summary': summary, 'sections': sections, 'citations': citations}


def query_alerts(session, user_message, user, query='', level='', only_unacknowledged=False, limit=8):
    started_at = time.time()
    normalized_query, level, only_unacknowledged = _normalize_alert_query_request(query, level, only_unacknowledged)
    tokens = _clean_alert_query_tokens(normalized_query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_alerts',
        {
            'raw_query': query,
            'query': normalized_query,
            'tokens': tokens,
            'level': level,
            'only_unacknowledged': only_unacknowledged,
            'limit': limit,
        },
    )
    if not user_has_permissions(user, ['ops.alert.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'error': '当前账号无权查看告警。', 'sections': [], 'citations': []}

    queryset = Alert.objects.select_related('host').all()
    if only_unacknowledged:
        queryset = queryset.filter(is_acknowledged=False)
    if level:
        queryset = queryset.filter(level=level)
    if tokens:
        queryset = _queryset_search(queryset, ['title', 'source', 'message', 'host__hostname'], tokens)
    alerts = list(queryset.order_by('-created_at')[:limit])
    counter = Counter(alert.level for alert in alerts)
    sections = [{
        'title': '告警明细',
        'items': [
            f'{alert.get_level_display()} / {alert.title} / {alert.source} / {alert.host.hostname if alert.host else "无主机关联"}'
            for alert in alerts
        ],
    }] if alerts else [{
        'title': '鍛婅鏄庣粏',
        'items': ['当前没有符合筛选条件的告警。'],
    }]
    citations = [{'title': '告警中心', 'path': '/alerts'}]
    response_summary = {
        'count': len(alerts),
        'critical': counter.get('critical', 0),
        'warning': counter.get('warning', 0),
        'info': counter.get('info', 0),
    }
    _finish_tool_invocation(invocation, response_summary, started_at, success=True)
    return {'summary': response_summary, 'sections': sections, 'citations': citations, 'alerts': alerts}


def query_events(session, user_message, user, query='', limit=8):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_events', {'query': query, 'tokens': tokens, 'limit': limit})
    if not user_has_permissions(user, ['eventwall.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = EventRecord.objects.all()
    queryset = _queryset_search(queryset, ['title', 'summary', 'resource_name', 'application', 'module'], tokens)
    events = list(queryset.order_by('-occurred_at')[:limit])
    sections = [{
        'title': '关键事件',
        'items': [f'{event.title} / {event.module} / {event.result}' for event in events],
    }] if events else []
    _finish_tool_invocation(invocation, {'count': len(events)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '事件总览', 'path': '/events/overview'}], 'events': events}


def query_logs(session, user_message, user, query='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_logs', {'query': query, 'tokens': tokens, 'limit': limit})
    allowed = user_has_permissions(user, ['ops.log.entry.view']) or user_has_permissions(user, ['ops.log.query'])
    if not allowed:
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = _queryset_search(LogEntry.objects.select_related('host').all(), ['service', 'message', 'host__hostname'], tokens)
    logs = list(queryset.order_by('-timestamp')[:limit])
    sections = [{
        'title': '相关日志',
        'items': [f'{log.get_level_display()} / {log.service} / {log.message[:80]}' for log in logs],
    }] if logs else []
    _finish_tool_invocation(invocation, {'count': len(logs)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '日志中心', 'path': '/logs/query'}], 'logs': logs}


def query_traces(session, user_message, user, query='', errors_only=False, limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_traces',
        {'query': query, 'tokens': tokens, 'errors_only': errors_only, 'limit': limit},
    )
    if not user_has_permissions(user, ['ops.trace.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    traces = []
    for item in DEMO_TRACES:
        haystack = ' '.join([item['trace_id'], item['service_name'], item['summary'], *item['endpoint_names']]).lower()
        if tokens and not all(token.lower() in haystack for token in tokens):
            continue
        if errors_only and not item['is_error']:
            continue
        traces.append(item)
    traces = traces[:limit]
    sections = [{
        'title': '链路追踪',
        'items': [f"{item['service_name']} / {item['state']} / {item['duration_ms']}ms / {item['summary']}" for item in traces],
    }] if traces else []
    _finish_tool_invocation(invocation, {'count': len(traces)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '链路追踪', 'path': '/observability/tracing'}], 'traces': traces}


def query_recent_changes(session, user_message, user, limit=5):
    started_at = time.time()
    invocation = _create_tool_invocation(session, user_message, 'query_recent_changes', {'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.deployment.view']):
        deployments = list(Deployment.objects.order_by('-deployed_at', '-executed_at', '-id')[:limit])
        if deployments:
            sections.append({
                'title': '最近发布',
                'items': [f'{item.app_name} / {item.version} / {item.get_status_display()}' for item in deployments],
            })
            citations.append({'title': '应用发布', 'path': '/deployments'})
    if user_has_permissions(user, ['ops.iac.view']):
        executions = list(TerraformExecution.objects.select_related('stack').order_by('-created_at')[:limit])
        if executions:
            sections.append({
                'title': '最近 IaC 执行',
                'items': [f'{item.stack.name} / {item.get_action_display()} / {item.get_status_display()}' for item in executions],
            })
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': citations}


def query_host_tasks(session, user_message, user, query='', status='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_host_tasks',
        {'query': query, 'tokens': tokens, 'status': status, 'limit': limit},
    )
    if not user_has_permissions(user, ['ops.host.execute']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    queryset = HostTask.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    queryset = _queryset_search(queryset, ['name', 'description', 'created_by', 'summary'], tokens)
    tasks = list(queryset.order_by('-created_at')[:limit])
    sections = [{
        'title': '任务中心',
        'items': [f'{task.name} / {task.get_status_display()} / {task.created_by}' for task in tasks],
    }] if tasks else []
    summary = {'count': len(tasks)}
    _finish_tool_invocation(invocation, summary, started_at, success=True)
    return {'summary': summary, 'sections': sections, 'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}], 'tasks': tasks}


def query_cmdb_items(session, user_message, user, query='', environment='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    environment = environment or _extract_environment(query)
    invocation = _create_tool_invocation(session, user_message, 'query_cmdb_items', {'query': query, 'environment': environment, 'limit': limit})
    if not user_has_permissions(user, ['cmdb.ci.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = ConfigItem.objects.select_related('ci_type').all()
    if environment:
        queryset = queryset.filter(environment=environment)
    queryset = _queryset_search(queryset, ['name', 'business_line', 'admin_user'], tokens)
    items = list(queryset.order_by('-updated_at')[:limit])
    sections = [{
        'title': 'CMDB 配置项',
        'items': [f'{item.name} / {item.ci_type.name} / {item.get_status_display()}' for item in items],
    }] if items else []
    _finish_tool_invocation(invocation, {'count': len(items)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': 'CMDB', 'path': '/cmdb', 'query': {'tab': 'items'}}], 'items': items}


def query_observability(session, user_message, user, query='', limit=6):
    alert_payload = query_alerts(session, user_message, user, query=query, limit=limit)
    log_payload = query_logs(session, user_message, user, query=query, limit=limit)
    trace_payload = query_traces(session, user_message, user, query=query, errors_only='异常' in (query or '') or '错误' in (query or ''), limit=limit)
    change_payload = query_recent_changes(session, user_message, user, limit=4)
    sections = []
    citations = []
    for payload in [alert_payload, log_payload, trace_payload, change_payload]:
        sections.extend(payload.get('sections', []))
        citations.extend(payload.get('citations', []))
    return {'sections': sections, 'citations': _dedupe_citations(citations)}


def query_workorders(session, user_message, user, query='', status='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_workorders', {'query': query, 'status': status, 'limit': limit})
    if not user_has_permissions(user, ['ops.ticket.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = TransactionTicket.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    queryset = _queryset_search(queryset, ['title', 'description', 'applicant', 'business_line'], tokens)
    tickets = list(queryset.order_by('-updated_at')[:limit])
    sections = [{
        'title': '工单系统',
        'items': [f'{item.title} / {item.get_ticket_type_display()} / {item.get_status_display()}' for item in tickets],
    }] if tickets else []
    _finish_tool_invocation(invocation, {'count': len(tickets)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '工单系统', 'path': '/workorders'}], 'tickets': tickets}


def query_task_center(session, user_message, user, query='', status='', limit=6):
    return query_host_tasks(session, user_message, user, query=query, status=status, limit=limit)


def query_event_wall(session, user_message, user, query='', limit=8):
    return query_events(session, user_message, user, query=query, limit=limit)


def query_container_assets(session, user_message, user, query='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_container_assets', {'query': query, 'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.k8s.view']):
        clusters = list(_queryset_search(K8sCluster.objects.all(), ['name', 'api_server', 'description'], tokens).order_by('-updated_at')[:limit])
        if clusters:
            sections.append({'title': 'Kubernetes 集群', 'items': [f'{item.name} / {item.get_status_display()}' for item in clusters]})
            citations.append({'title': 'K8s 集群', 'path': '/containers/k8s'})
    if user_has_permissions(user, ['ops.docker.view']):
        hosts = list(_queryset_search(DockerHost.objects.all(), ['name', 'ip_address', 'description'], tokens).order_by('-updated_at')[:limit])
        if hosts:
            sections.append({'title': 'Docker 主机', 'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in hosts]})
            citations.append({'title': 'Docker 环境', 'path': '/containers/docker'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': citations}


def query_middleware_assets(session, user_message, user, query='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_middleware_assets', {'query': query, 'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.nginx.view']):
        nginx_envs = list(_queryset_search(NginxEnvironment.objects.all(), ['name', 'ip_address', 'description'], tokens).order_by('-updated_at')[:limit])
        if nginx_envs:
            sections.append({'title': 'Nginx 环境', 'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in nginx_envs]})
            citations.append({'title': 'Nginx 管理', 'path': '/middleware/nginx'})
    if user_has_permissions(user, ['ops.middleware.view']):
        payload = build_middleware_payload(get_middleware_demo_state())
        redis_summary = payload.get('redis', {}).get('summary', {})
        rocketmq_summary = payload.get('rocketmq', {}).get('summary', {})
        es_summary = payload.get('elasticsearch', {}).get('summary', {})
        sections.append({
            'title': '中间件概览',
            'items': [
                f"Redis / 集群 {redis_summary.get('cluster_count', 0)} / 告警 {redis_summary.get('warning_count', 0)}",
                f"RocketMQ / 集群 {rocketmq_summary.get('cluster_count', 0)} / 告警 {rocketmq_summary.get('warning_count', 0)}",
                f"Elasticsearch / 集群 {es_summary.get('cluster_count', 0)} / 告警 {es_summary.get('warning_count', 0)}",
            ],
        })
        citations.append({'title': '中间件', 'path': '/middleware/manage'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': _dedupe_citations(citations)}


def build_markdown_answer(title, sections, citations, intro=''):
    lines = []
    if intro:
        lines.append(intro)
        lines.append('')
    if title:
        lines.append(f'**{title}**')
    for section in sections:
        lines.append(f"- {section['title']}")
        for item in section.get('items', []):
            lines.append(f'  {item}')
    if citations:
        lines.append('')
        lines.append('可继续查看：' + '、'.join(item['title'] for item in _dedupe_citations(citations)))
    return '\n'.join(lines).strip()


def _build_task_sections(draft):
    sections = [{
        'title': '任务草稿',
        'items': [
            f"任务名称：{draft['name']}",
            f"任务类型：{draft['task_type']}",
            f"目标主机：{draft['host_count']} 台",
            f"执行方式：{draft['execution_mode']}",
            f"执行策略：{draft['execution_strategy']}",
            f"风险等级：{draft['risk_level']}",
        ],
    }]
    payload = draft.get('payload') or {}
    if payload.get('command'):
        sections.append({'title': '命令内容', 'items': [payload['command']]})
    if payload.get('service_name'):
        sections.append({'title': '服务名称', 'items': [payload['service_name']]})
    if payload.get('playbook_content'):
        sections.append({'title': 'Playbook 摘要', 'items': ['已生成内联 Playbook 草稿']})
    return sections


def build_task_draft(user, question='', draft_request=None):
    if not user_has_permissions(user, ['aiops.task.generate']):
        return {'error': '当前账号无权生成任务草稿。'}

    draft_request = draft_request or {}
    environment = draft_request.get('environment') or _extract_environment(question)
    target_status = draft_request.get('target_status') or ('offline' if '离线' in (question or '') else 'all')
    max_hosts = draft_request.get('max_hosts') or 20

    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if target_status == 'offline':
        host_queryset = host_queryset.filter(status='offline')

    explicit_host_ids = draft_request.get('target_host_ids') or []
    if explicit_host_ids:
        host_ids = list(Host.objects.filter(id__in=explicit_host_ids).values_list('id', flat=True))
    else:
        host_ids = list(host_queryset.values_list('id', flat=True)[:max_hosts])
    if not host_ids:
        host_ids = list(Host.objects.values_list('id', flat=True)[: min(max_hosts, 10)])
    if not host_ids:
        return {'error': '当前没有可用主机，无法生成任务。'}

    task_kind = draft_request.get('task_kind') or ''
    service_name = (draft_request.get('service_name') or '').strip()
    command = (draft_request.get('command') or '').strip()
    playbook_content = (draft_request.get('playbook_content') or '').strip()
    request_summary = (draft_request.get('request_summary') or question or '').strip()

    if not task_kind:
        service_match = re.search(r'(nginx|redis|rocketmq|mysql|docker|kubelet|sshd)', question or '', re.IGNORECASE)
        command_match = re.search(r'(?:执行|运行|命令)\s+([a-zA-Z0-9_\-./ ]{3,120})', question or '')
        if service_name or service_match:
            task_kind = 'service_status'
            service_name = service_name or service_match.group(1)
        elif command or command_match:
            task_kind = 'run_command'
            command = command or command_match.group(1).strip()
        elif _contains_any(question, ['连通', '连通性', 'ssh']):
            task_kind = 'check_connection'
        elif _contains_any(question, ['playbook']):
            task_kind = 'run_playbook'
        else:
            task_kind = 'refresh_metrics'

    task_type = HostTask.TASK_REFRESH_METRICS
    payload = {}
    execution_mode = HostTask.EXECUTION_MODE_SSH
    execution_strategy = HostTask.STRATEGY_CONTINUE
    timeout_seconds = 30
    title = '智能巡检任务'
    description = '由 AIOps 智能助手生成的任务草稿'

    if task_kind == 'service_status':
        task_type = HostTask.TASK_SERVICE_STATUS
        payload = {'service_name': service_name or 'nginx'}
        title = f"{payload['service_name']} 服务状态巡检"
        description = f"检查 {payload['service_name']} 服务状态"
    elif task_kind == 'run_command':
        task_type = HostTask.TASK_RUN_COMMAND
        payload = {'command': command or 'hostname && uptime'}
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        execution_strategy = HostTask.STRATEGY_STOP_ON_ERROR
        title = f"批量命令执行：{payload['command'][:32]}"
        description = '由聊天助手从自然语言生成的批量命令任务'
    elif task_kind == 'check_connection':
        task_type = HostTask.TASK_CHECK_CONNECTION
        title = 'SSH 连通性检查'
        description = '检查目标主机 SSH 连通性'
    elif task_kind == 'run_playbook':
        task_type = HostTask.TASK_RUN_PLAYBOOK
        payload = {
            'playbook_name': 'aiops_generated',
            'playbook_content': playbook_content or '- hosts: all\n  gather_facts: false\n  tasks:\n    - name: ping\n      ping:\n',
        }
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        title = 'Ansible Playbook 执行'
        description = '由 AIOps 智能助手生成的 Playbook 任务'

    risk_level = AIOpsPendingAction.RISK_LOW
    if task_type == HostTask.TASK_RUN_COMMAND:
        risk_level = AIOpsPendingAction.RISK_HIGH
        lowered_command = payload.get('command', '').lower()
        if any(pattern in lowered_command for pattern in DANGEROUS_COMMAND_PATTERNS):
            risk_level = AIOpsPendingAction.RISK_CRITICAL
    elif task_type == HostTask.TASK_RUN_PLAYBOOK:
        risk_level = AIOpsPendingAction.RISK_HIGH
    elif task_type == HostTask.TASK_SERVICE_STATUS:
        risk_level = AIOpsPendingAction.RISK_MEDIUM

    return {
        'name': title,
        'description': description,
        'task_type': task_type,
        'payload': payload,
        'host_ids': host_ids,
        'execution_mode': execution_mode,
        'execution_strategy': execution_strategy,
        'timeout_seconds': timeout_seconds,
        'host_count': len(host_ids),
        'risk_level': risk_level,
        'request_summary': request_summary,
    }


def create_pending_task_action_from_draft(session, assistant_message, draft):
    return AIOpsPendingAction.objects.create(
        session=session,
        message=assistant_message,
        action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
        title=draft['name'],
        risk_level=draft['risk_level'],
        action_payload=draft,
    )


def create_pending_task_action(session, assistant_message, user, question):
    draft = build_task_draft(user, question)
    if draft.get('error'):
        return None, draft['error']
    return create_pending_task_action_from_draft(session, assistant_message, draft), ''


def _execute_host_task_action(action, user, request=None):
    payload = dict(action.action_payload or {})
    host_ids = payload.get('host_ids') or []
    host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
    hosts = [host_map[item] for item in host_ids if item in host_map]
    if not hosts:
        raise ValueError('没有找到有效的目标主机。')

    task = HostTask.objects.create(
        name=payload.get('name') or 'AIOps 智能任务',
        task_type=payload.get('task_type') or HostTask.TASK_REFRESH_METRICS,
        description=payload.get('description', ''),
        payload=payload.get('payload') or {},
        selection_filters={'source': 'aiops', 'session_id': action.session_id},
        execution_mode=payload.get('execution_mode') or HostTask.EXECUTION_MODE_SSH,
        execution_strategy=payload.get('execution_strategy') or HostTask.STRATEGY_CONTINUE,
        timeout_seconds=payload.get('timeout_seconds') or 30,
        created_by=user.username,
        summary='任务已由 AIOps 智能助手创建，等待执行完成',
    )
    start_host_task(task, hosts)
    action.status = AIOpsPendingAction.STATUS_EXECUTED
    action.result_payload = {'task_id': task.id, 'task_name': task.name}
    action.save(update_fields=['status', 'result_payload', 'updated_at'])
    record_event(
        request=request,
        module='aiops',
        category='execution',
        action='confirm_execute_task',
        title='AIOps 执行主机任务',
        summary=f'已通过 AIOps 执行主机任务 {task.name}',
        resource_type='aiops_action',
        resource_id=action.id,
        resource_name=action.title,
        correlation_id=f'aiops-action:{action.id}',
        related_resources=[{'module': 'ops', 'type': 'host_task', 'id': str(task.id), 'name': task.name}],
        metadata={'host_count': len(hosts), 'created_by': user.username},
    )
    return task


def confirm_action(action, user, request=None):
    config = get_agent_config()
    if not config.allow_action_execution:
        raise ValueError('管理员已关闭机器人动作执行。')
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可确认。')
    if action.session.user_id != user.id:
        raise ValueError('只能确认自己的动作。')
    if action.action_type == AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK:
        if not user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
            raise ValueError('当前账号无权执行机器人任务。')
        action.status = AIOpsPendingAction.STATUS_CONFIRMED
        action.confirmed_by = user.username
        action.confirmed_at = timezone.now()
        action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
        return _execute_host_task_action(action, user, request=request)
    raise ValueError('不支持的动作类型。')


def cancel_action(action, user):
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可取消。')
    if action.session.user_id != user.id:
        raise ValueError('只能取消自己的动作。')
    action.status = AIOpsPendingAction.STATUS_CANCELED
    action.confirmed_by = user.username
    action.confirmed_at = timezone.now()
    action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
    return action


def _provider_is_ready(provider):
    return bool(provider and provider.base_url and provider.get_api_key() and provider.default_model)


def _build_dispatch_error_result(detail='', code='error', message='问答失败，请稍后重试。'):
    error_detail = (detail or '')[:500]
    content = message
    if error_detail:
        content = f'{content}\n\n{error_detail}'
    return {
        'content': content,
        'citations': [],
        'tool_calls': [],
        'message_type': AIOpsChatMessage.TYPE_ERROR,
        'pending_action_draft': None,
        'metadata': {'execution_mode': 'error', 'error_code': code, 'error_detail': error_detail},
    }


def _candidate_model_names(model_name):
    model_name = (model_name or '').strip()
    if not model_name:
        return []
    candidates = [model_name]
    if re.fullmatch(r'gpt-5(?:\.\d+)?', model_name):
        candidates.extend([f'{model_name}-low', f'{model_name}-medium'])
    return list(dict.fromkeys(candidates))


def _extract_message_content(message):
    content = (message or {}).get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                parts.append(item['text'])
        return '\n'.join(parts)
    return ''


def _sanitize_assistant_content(content):
    text = (content or '').strip()
    if not text:
        return ''
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.S | re.I)
    return text.strip()


def _request_model_completion(provider, payload):
    endpoint = provider.base_url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint = f'{endpoint}/chat/completions'
    headers = {
        'Authorization': f'Bearer {provider.get_api_key()}',
        'Content-Type': 'application/json',
    }
    last_error = '模型调用失败'

    for model_name in _candidate_model_names(payload.get('model')):
        request_payload = {**payload, 'model': model_name}
        response = requests.post(
            endpoint,
            headers=headers,
            json=request_payload,
            timeout=max(provider.timeout_seconds, 5),
        )
        try:
            data = response.json()
        except ValueError:
            data = {'status_code': response.status_code, 'text': response.text[:800]}
        if response.status_code >= 400:
            last_error = data
            continue
        choice = ((data or {}).get('choices') or [{}])[0]
        message = choice.get('message') or {}
        content = _sanitize_assistant_content(_extract_message_content(message))
        if content or (message.get('tool_calls') or []):
            if content != _extract_message_content(message):
                message['content'] = content
                choice['message'] = message
                data['choices'][0] = choice
            if model_name != payload.get('model'):
                data.setdefault('_meta', {})['resolved_model'] = model_name
            return data
        last_error = {'error': {'message': f'model {model_name} returned empty content', 'type': 'empty_content'}}

    raise ValueError(last_error)


def test_model_provider_connection(provider):
    if not _provider_is_ready(provider):
        return {'status': 'failed', 'message': '请完善 Base URL、模型和 API Key'}
    result = _request_model_completion(provider, {
        'model': provider.default_model,
        'temperature': 0,
        'max_tokens': 32,
        'messages': [{'role': 'user', 'content': '请只回复：连接成功'}],
    })
    resolved_model = ((result or {}).get('_meta') or {}).get('resolved_model') or provider.default_model
    return {
        'status': 'success',
        'message': f'模型连接成功（实际调用模型：{resolved_model}）',
        'resolved_model': resolved_model,
    }


def _safe_tool_name(value):
    normalized = re.sub(r'[^a-zA-Z0-9_]+', '_', str(value or '').strip())
    normalized = re.sub(r'_+', '_', normalized).strip('_')
    return normalized or 'tool'


def _build_mcp_tool_alias(server, raw_tool_name):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        return raw_tool_name
    return f"mcp__{_safe_tool_name(server.name)}__{_safe_tool_name(raw_tool_name)}"


def _extract_mcp_headers(response):
    headers = {}
    for key, value in response.headers.items():
        headers[key.lower()] = value
    return headers


def _parse_sse_json_messages(payload_text):
    messages = []
    data_lines = []
    for line in (payload_text or '').splitlines():
        if line.startswith('data:'):
            data_lines.append(line[5:].strip())
            continue
        if not line.strip() and data_lines:
            chunk = '\n'.join(data_lines)
            data_lines = []
            if not chunk:
                continue
            try:
                messages.append(json.loads(chunk))
            except (TypeError, ValueError):
                continue
    if data_lines:
        try:
            messages.append(json.loads('\n'.join(data_lines)))
        except (TypeError, ValueError):
            pass
    return messages


def _extract_jsonrpc_messages_from_http_response(response):
    content_type = (response.headers.get('Content-Type') or '').lower()
    if 'text/event-stream' in content_type:
        return _parse_sse_json_messages(response.text)
    if not response.content:
        return []
    payload = response.json()
    if isinstance(payload, list):
        return payload
    return [payload]


class _BaseMCPClientSession:
    def __init__(self, server):
        self.server = server
        self.protocol_version = MCP_PROTOCOL_VERSION

    def initialize(self):
        raise NotImplementedError

    def list_tools(self):
        raise NotImplementedError

    def call_tool(self, name, arguments):
        raise NotImplementedError

    def close(self):
        return None


class _HTTPMCPClientSession(_BaseMCPClientSession):
    def __init__(self, server):
        super().__init__(server)
        self.session = requests.Session()
        self.session_id = ''
        auth_config = server.auth_config or {}
        self.timeout_seconds = max(int(auth_config.get('timeout_seconds') or 20), 5)
        self.extra_headers = dict(auth_config.get('headers') or {})
        if auth_config.get('bearer_token'):
            self.extra_headers.setdefault('Authorization', f"Bearer {auth_config['bearer_token']}")

    def _post(self, message, include_session=True):
        headers = {
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
            'MCP-Protocol-Version': self.protocol_version,
            **self.extra_headers,
        }
        if include_session and self.session_id:
            headers['MCP-Session-Id'] = self.session_id
        response = self.session.post(
            self.server.endpoint_or_command,
            json=message,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise ValueError(response.text or f'HTTP {response.status_code}')
        header_map = _extract_mcp_headers(response)
        if header_map.get('mcp-session-id'):
            self.session_id = header_map['mcp-session-id']
        return _extract_jsonrpc_messages_from_http_response(response)

    def _delete_session(self):
        if not self.session_id:
            return
        headers = {'MCP-Session-Id': self.session_id, **self.extra_headers}
        try:
            self.session.delete(self.server.endpoint_or_command, headers=headers, timeout=self.timeout_seconds)
        except Exception:
            pass

    def _request(self, method, params=None):
        request_id = uuid.uuid4().hex
        responses = self._post({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        for item in responses:
            if str(item.get('id')) != request_id:
                continue
            if item.get('error'):
                raise ValueError(item['error'])
            return item.get('result') or {}
        return {}

    def _notify(self, method, params=None):
        self._post({'jsonrpc': '2.0', 'method': method, 'params': params or {}}, include_session=True)

    def initialize(self):
        result = self._request(
            'initialize',
            {'protocolVersion': self.protocol_version, 'capabilities': {}, 'clientInfo': MCP_CLIENT_INFO},
        )
        self.protocol_version = result.get('protocolVersion') or self.protocol_version
        self._notify('notifications/initialized', {})
        return result

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            params = {'cursor': cursor} if cursor else {}
            result = self._request('tools/list', params)
            tools.extend(result.get('tools') or [])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(self, name, arguments):
        return self._request('tools/call', {'name': name, 'arguments': arguments or {}})

    def close(self):
        self._delete_session()
        self.session.close()


class _StdioMCPClientSession(_BaseMCPClientSession):
    def __init__(self, server):
        super().__init__(server)
        auth_config = server.auth_config or {}
        command = shlex.split(server.endpoint_or_command or '', posix=False)
        if not command:
            raise ValueError('MCP STDIO command is empty')
        env = dict(os.environ)
        env.update(auth_config.get('env') or {})
        self.timeout_seconds = max(int(auth_config.get('timeout_seconds') or 20), 5)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
        )
        self.stdout_queue = queue.Queue()
        self.stderr_queue = queue.Queue()
        self._start_reader(self.process.stdout, self.stdout_queue)
        self._start_reader(self.process.stderr, self.stderr_queue)

    def _start_reader(self, stream, target_queue):
        def pump():
            for line in iter(stream.readline, ''):
                target_queue.put(line)
        thread = threading.Thread(target=pump, daemon=True)
        thread.start()

    def _send(self, payload):
        if not self.process.stdin:
            raise ValueError('MCP STDIO stdin unavailable')
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def _request(self, method, params=None):
        request_id = uuid.uuid4().hex
        self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            try:
                line = self.stdout_queue.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except (TypeError, ValueError):
                continue
            if str(message.get('id')) != request_id:
                continue
            if message.get('error'):
                raise ValueError(message['error'])
            return message.get('result') or {}
        stderr_output = []
        while not self.stderr_queue.empty():
            stderr_output.append(self.stderr_queue.get_nowait().strip())
        raise TimeoutError('MCP STDIO request timed out: ' + ' '.join(item for item in stderr_output if item))

    def _notify(self, method, params=None):
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def initialize(self):
        result = self._request(
            'initialize',
            {'protocolVersion': self.protocol_version, 'capabilities': {}, 'clientInfo': MCP_CLIENT_INFO},
        )
        self.protocol_version = result.get('protocolVersion') or self.protocol_version
        self._notify('notifications/initialized', {})
        return result

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            params = {'cursor': cursor} if cursor else {}
            result = self._request('tools/list', params)
            tools.extend(result.get('tools') or [])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(self, name, arguments):
        return self._request('tools/call', {'name': name, 'arguments': arguments or {}})

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _create_mcp_client_session(server):
    if server.server_type == AIOpsMCPServer.SERVER_HTTP:
        return _HTTPMCPClientSession(server)
    if server.server_type == AIOpsMCPServer.SERVER_STDIO:
        return _StdioMCPClientSession(server)
    raise ValueError(f'Unsupported MCP server type: {server.server_type}')


def test_mcp_server_connection(server):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        return {
            'status': 'success',
            'message': '内置 MCP 无需额外握手，当前可直接使用。',
            'server_info': {'name': server.name, 'type': server.server_type},
        }

    client_session = _create_mcp_client_session(server)
    try:
        result = client_session.initialize()
        return {
            'status': 'success',
            'message': 'MCP 连接成功。',
            'server_info': result.get('serverInfo') or {'name': server.name},
            'protocol_version': result.get('protocolVersion') or MCP_PROTOCOL_VERSION,
            'capabilities': result.get('capabilities') or {},
        }
    finally:
        try:
            client_session.close()
        except Exception:
            pass


def list_mcp_server_tools(server):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        tool_names = server.tool_whitelist or []
        return {
            'tools': [
                {'name': item, 'description': '平台内置 MCP 工具', 'inputSchema': {'type': 'object', 'properties': {}}}
                for item in tool_names
            ],
            'count': len(tool_names),
        }

    client_session = _create_mcp_client_session(server)
    try:
        client_session.initialize()
        tools = _discover_external_mcp_tools(server, client_session)
        return {'tools': tools, 'count': len(tools)}
    finally:
        try:
            client_session.close()
        except Exception:
            pass


def _build_runtime_prompt(config, active_mcp_servers, active_skills, user):
    mcp_lines = [
        f"- {server.name}：{server.description}；工具：{'、'.join(server.tool_whitelist or [])}"
        for server in active_mcp_servers
    ]
    skill_lines = [f"- {skill.name}：{skill.content}" for skill in active_skills]
    permission_lines = [
        f"- 可聊天：{'是' if user_has_permissions(user, ['aiops.chat.view']) else '否'}",
        f"- 可分析：{'是' if user_has_permissions(user, ['aiops.chat.analyze']) else '否'}",
        f"- 可生成任务：{'是' if user_has_permissions(user, ['aiops.task.generate']) else '否'}",
        f"- 可执行任务：{'是' if user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']) else '否'}",
    ]
    runtime_lines = [
        f"- allow_action_execution={config.allow_action_execution}",
        f"- require_confirmation={config.require_confirmation}",
        f"- show_evidence={config.show_evidence}",
    ]
    parts = [
        config.system_prompt or DEFAULT_SYSTEM_PROMPT,
        '你当前接入的是平台内置 MCP 与 Skills 运行时。',
        '可用 MCP：',
        '\n'.join(mcp_lines) if mcp_lines else '- 当前无可用 MCP',
        '启用 Skill：',
        '\n'.join(skill_lines) if skill_lines else '- 当前无启用 Skill',
        '当前用户权限：',
        '\n'.join(permission_lines),
        '运行约束：',
        '\n'.join(runtime_lines),
        '要求：优先调用工具获取事实；未确认前不能声称任务已执行；如果数据不足，请明确说明。',
    ]
    return '\n'.join(parts)


def _build_history_messages(session, config):
    history = list(session.messages.order_by('-created_at', '-id')[: max(config.max_history_messages, 4)])
    history.reverse()
    return [
        {'role': item.role, 'content': item.content}
        for item in history
        if item.role in {AIOpsChatMessage.ROLE_USER, AIOpsChatMessage.ROLE_ASSISTANT}
    ]


def _tool_allowed(user, tool_name):
    if tool_name == 'query_cmdb_items':
        return user_has_permissions(user, ['cmdb.ci.view'])
    if tool_name == 'query_observability':
        return any([
            user_has_permissions(user, ['ops.alert.view']),
            user_has_permissions(user, ['ops.log.entry.view']),
            user_has_permissions(user, ['ops.log.query']),
            user_has_permissions(user, ['ops.trace.view']),
            user_has_permissions(user, ['ops.deployment.view']),
            user_has_permissions(user, ['ops.iac.view']),
        ])
    if tool_name == 'query_workorders':
        return user_has_permissions(user, ['ops.ticket.view'])
    if tool_name == 'query_task_center':
        return user_has_permissions(user, ['ops.host.execute'])
    if tool_name == 'query_event_wall':
        return user_has_permissions(user, ['eventwall.view'])
    if tool_name == 'query_container_assets':
        return user_has_permissions(user, ['ops.k8s.view']) or user_has_permissions(user, ['ops.docker.view'])
    if tool_name == 'query_middleware_assets':
        return user_has_permissions(user, ['ops.nginx.view']) or user_has_permissions(user, ['ops.middleware.view'])
    if tool_name == 'query_resources':
        return any([
            user_has_permissions(user, ['ops.host.view']),
            user_has_permissions(user, ['cmdb.ci.view']),
            user_has_permissions(user, ['ops.multicloud.view']),
            user_has_permissions(user, ['ops.iac.view']),
            user_has_permissions(user, ['ops.k8s.view']),
            user_has_permissions(user, ['ops.docker.view']),
            user_has_permissions(user, ['ops.nginx.view']),
            user_has_permissions(user, ['ops.log.datasource.view']),
        ])
    if tool_name == 'query_alerts':
        return user_has_permissions(user, ['ops.alert.view'])
    if tool_name == 'query_events':
        return user_has_permissions(user, ['eventwall.view'])
    if tool_name == 'query_logs':
        return user_has_permissions(user, ['ops.log.entry.view']) or user_has_permissions(user, ['ops.log.query'])
    if tool_name == 'query_traces':
        return user_has_permissions(user, ['ops.trace.view'])
    if tool_name == 'query_recent_changes':
        return user_has_permissions(user, ['ops.deployment.view']) or user_has_permissions(user, ['ops.iac.view'])
    if tool_name == 'query_host_tasks':
        return user_has_permissions(user, ['ops.host.execute'])
    if tool_name == 'generate_host_task':
        return user_has_permissions(user, ['aiops.task.generate'])
    return False


def _tool_specs_for_runtime(active_mcp_servers, user):
    tool_names = []
    for server in active_mcp_servers:
        for tool_name in server.tool_whitelist or []:
            if tool_name not in tool_names and _tool_allowed(user, tool_name):
                tool_names.append(tool_name)

    catalog = {
        'query_cmdb_items': {
            'description': '查询平台 CMDB 配置项。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_observability': {
            'description': '查询可观测性信息，包括告警、日志、链路与最近变更。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_workorders': {
            'description': '查询工单系统中的事务工单。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_task_center': {
            'description': '查询任务中心中的主机任务。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['pending', 'running', 'success', 'partial', 'failed', 'canceled']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_event_wall': {
            'description': '查询事件墙中的关键事件。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_container_assets': {
            'description': '查询容器管理中的 Kubernetes 集群与 Docker 主机。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_middleware_assets': {
            'description': '查询中间件管理中的 Nginx、Redis、RocketMQ、Elasticsearch 状态。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_resources': {
            'description': '查询平台资源，包括主机、CMDB、多云、IaC、中间件与日志数据源。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_alerts': {
            'description': '查询告警中心中的告警。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'level': {'type': 'string', 'enum': ['critical', 'warning', 'info']}, 'only_unacknowledged': {'type': 'boolean'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_events': {
            'description': '查询事件墙中的关键事件。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_logs': {
            'description': '查询日志中心日志。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_traces': {
            'description': '查询链路追踪数据。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'errors_only': {'type': 'boolean'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_recent_changes': {
            'description': '查询最近发布与 IaC 变更。',
            'parameters': {'type': 'object', 'properties': {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_host_tasks': {
            'description': '查询任务中心的主机任务。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['pending', 'running', 'success', 'partial', 'failed', 'canceled']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'generate_host_task': {
            'description': '生成任务中心主机任务草稿，默认进入待确认状态。',
            'parameters': {'type': 'object', 'properties': {'request_summary': {'type': 'string'}, 'task_kind': {'type': 'string', 'enum': ['refresh_metrics', 'service_status', 'run_command', 'check_connection', 'run_playbook']}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'target_status': {'type': 'string', 'enum': ['all', 'offline']}, 'service_name': {'type': 'string'}, 'command': {'type': 'string'}, 'playbook_content': {'type': 'string'}, 'target_host_ids': {'type': 'array', 'items': {'type': 'integer'}}, 'max_hosts': {'type': 'integer', 'minimum': 1, 'maximum': 50}}},
        },
    }

    catalog['query_alerts'] = {
        'description': '查询告警中心中的告警。涉及级别或确认状态时，优先填写 level 与 only_unacknowledged；query 只保留主机名、服务名、告警标题等关键词，不要把 severity、acknowledged、status 之类过滤条件写进 query。',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': '仅用于主机名、服务名、告警标题、来源等文本检索；不用于级别和确认状态过滤。',
                },
                'level': {
                    'type': 'string',
                    'enum': ['critical', 'warning', 'info'],
                    'description': '告警级别。用户提到严重/高危时填 critical，提到警告时填 warning。',
                },
                'only_unacknowledged': {
                    'type': 'boolean',
                    'description': '只看未确认告警。用户提到未确认、未认领、未处理时填 true。',
                },
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
        },
    }

    catalog['query_observability'] = {
        'description': '查询可观测性综合信息，用于跨告警、日志、链路、变更做关联分析。若用户只是在直接查询告警列表、告警数量、严重级别或确认状态，优先使用 query_alerts，不要改用本工具。',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
        },
    }

    return [
        {'type': 'function', 'function': {'name': tool_name, 'description': catalog[tool_name]['description'], 'parameters': catalog[tool_name]['parameters']}}
        for tool_name in tool_names
        if tool_name in catalog
    ]


def _discover_external_mcp_tools(server, client_session):
    whitelist = set(server.tool_whitelist or [])
    discovered = []
    for tool in client_session.list_tools():
        raw_name = tool.get('name')
        if not raw_name:
            continue
        if whitelist and raw_name not in whitelist:
            continue
        discovered.append(tool)
    return discovered


def _build_runtime_tool_registry(active_mcp_servers, user):
    tool_specs = []
    registry = {}
    managed_clients = []

    builtin_specs = _tool_specs_for_runtime([item for item in active_mcp_servers if item.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN], user)
    tool_specs.extend(builtin_specs)
    for spec in builtin_specs:
        registry[spec['function']['name']] = {'kind': 'internal', 'tool_name': spec['function']['name']}

    for server in active_mcp_servers:
        if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
            continue
        try:
            client_session = _create_mcp_client_session(server)
            client_session.initialize()
            managed_clients.append(client_session)
            for tool in _discover_external_mcp_tools(server, client_session):
                raw_name = tool.get('name')
                alias_name = _build_mcp_tool_alias(server, raw_name)
                description = tool.get('description') or f'{server.name} / {raw_name}'
                input_schema = tool.get('inputSchema') or {'type': 'object', 'properties': {}}
                tool_specs.append({
                    'type': 'function',
                    'function': {'name': alias_name, 'description': description, 'parameters': input_schema},
                })
                registry[alias_name] = {
                    'kind': 'external',
                    'server': server,
                    'client_session': client_session,
                    'raw_tool_name': raw_name,
                }
        except Exception:
            if 'client_session' in locals():
                try:
                    client_session.close()
                except Exception:
                    pass
            continue
    return tool_specs, registry, managed_clients


def _summarize_external_tool_result(registry_entry, result):
    server = registry_entry['server']
    raw_tool_name = registry_entry['raw_tool_name']
    items = []
    for content_item in result.get('content') or []:
        if content_item.get('type') == 'text' and content_item.get('text'):
            items.append(content_item['text'][:200])
    if not items and result.get('structuredContent'):
        items.append(json.dumps(result.get('structuredContent'), ensure_ascii=False, default=_json_default)[:240])
    if not items:
        items.append('外部 MCP 工具已返回结果。')
    return {
        'tool_output': result,
        'sections': [{'title': f"{server.name} / {raw_tool_name}", 'items': items[:4]}],
        'citations': [],
        'message_type': AIOpsChatMessage.TYPE_TEXT,
    }


def _parse_tool_arguments(raw_arguments):
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not raw_arguments:
        return {}
    try:
        return json.loads(raw_arguments)
    except (TypeError, ValueError):
        return {}


def _run_tool_call(session, user_message, user, tool_name, arguments, registry_entry=None):
    if registry_entry and registry_entry.get('kind') == 'external':
        started_at = time.time()
        invocation = _create_tool_invocation(
            session,
            user_message,
            f"mcp::{registry_entry['server'].name}::{registry_entry['raw_tool_name']}",
            arguments,
        )
        try:
            result = registry_entry['client_session'].call_tool(registry_entry['raw_tool_name'], arguments)
            _finish_tool_invocation(
                invocation,
                {'server': registry_entry['server'].name, 'tool': registry_entry['raw_tool_name'], 'is_error': bool(result.get('isError'))},
                started_at,
                success=not bool(result.get('isError')),
            )
            return _summarize_external_tool_result(registry_entry, result)
        except Exception as exc:
            _finish_tool_invocation(invocation, {'error': str(exc)}, started_at, success=False)
            return {
                'tool_output': {'error': str(exc)},
                'sections': [{'title': f"{registry_entry['server'].name} / {registry_entry['raw_tool_name']}", 'items': [str(exc)]}],
                'citations': [],
                'message_type': AIOpsChatMessage.TYPE_TEXT,
            }

    if tool_name == 'query_cmdb_items':
        result = query_cmdb_items(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_observability':
        result = query_observability(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_workorders':
        result = query_workorders(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_task_center':
        result = query_task_center(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_event_wall':
        result = query_event_wall(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_container_assets':
        result = query_container_assets(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_middleware_assets':
        result = query_middleware_assets(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_resources':
        result = query_resources(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_alerts':
        result = query_alerts(session, user_message, user, query=arguments.get('query', ''), level=arguments.get('level', ''), only_unacknowledged=bool(arguments.get('only_unacknowledged')), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_events':
        result = query_events(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_logs':
        result = query_logs(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_traces':
        result = query_traces(session, user_message, user, query=arguments.get('query', ''), errors_only=bool(arguments.get('errors_only')), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_recent_changes':
        result = query_recent_changes(session, user_message, user, limit=arguments.get('limit') or 5)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_host_tasks':
        result = query_host_tasks(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'generate_host_task':
        started_at = time.time()
        invocation = _create_tool_invocation(session, user_message, 'generate_host_task', arguments)
        draft = build_task_draft(user, arguments.get('request_summary', ''), draft_request=arguments)
        if draft.get('error'):
            _finish_tool_invocation(invocation, {'detail': draft['error']}, started_at, success=False)
            return {'tool_output': draft, 'sections': [], 'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}], 'message_type': AIOpsChatMessage.TYPE_ACTION}
        summary = {'name': draft['name'], 'task_type': draft['task_type'], 'host_count': draft['host_count'], 'risk_level': draft['risk_level']}
        _finish_tool_invocation(invocation, summary, started_at, success=True)
        return {
            'tool_output': {'draft': summary, 'requires_confirmation': True},
            'sections': _build_task_sections(draft),
            'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}],
            'message_type': AIOpsChatMessage.TYPE_ACTION,
            'pending_action_draft': draft,
        }
    raise ValueError(f'Unsupported tool: {tool_name}')


def _dispatch_with_tool_runtime(session, user_message, user, question, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    config = get_agent_config()
    provider = get_active_provider(config)
    if not _provider_is_ready(provider):
        emit(
            step={
                'title': '未配置可用模型',
                'detail': '请先在智能体配置中启用并测试默认模型提供商。',
                'status': PROCESSING_STATUS_FAILED,
            },
            text='当前没有可用模型',
        )
        return _build_dispatch_error_result(
            '未配置可用模型，请先在“智能体配置 / 模型提供商”中启用并测试默认模型。',
            code='provider_unavailable',
            message='当前没有可用模型，无法发起问答。',
        )

    active_mcp_servers = _get_selected_mcp_servers(config)
    active_skills = _get_selected_skills(config, user=user)
    tools, registry, managed_clients = _build_runtime_tool_registry(active_mcp_servers, user)
    if not tools:
        emit(
            step={
                'title': '\u672a\u53d1\u73b0\u53ef\u7528 MCP \u5de5\u5177',
                'detail': '当前未启用任何 MCP 工具，请先在智能体配置中启用至少一个 MCP。',
                'status': PROCESSING_STATUS_FAILED,
            },
            text='当前没有可用工具',
        )
        return _build_dispatch_error_result(
            '当前未启用任何 MCP 工具，请先在“智能体配置 / MCP”中启用至少一个工具。',
            code='tool_unavailable',
            message='当前没有可用工具，无法处理该问题。',
        )

    emit(
        step={
            'title': '\u52a0\u8f7d MCP \u4e0e Skill',
            'detail': f'\u5df2\u542f\u7528 {len(active_mcp_servers)} \u4e2a MCP\uff0c{len(active_skills)} \u4e2a Skill\u3002',
            'status': PROCESSING_STATUS_COMPLETED,
        },
        text='\u6b63\u5728\u89c4\u5212\u5de5\u5177\u8c03\u7528',
    )

    messages = [
        {'role': 'system', 'content': _build_runtime_prompt(config, active_mcp_servers, active_skills, user)},
        *_build_history_messages(session, config),
    ]

    executed_tool_names = []
    sections = []
    citations = []
    pending_action_draft = None
    message_type = AIOpsChatMessage.TYPE_TEXT
    final_content = ''

    try:
        for round_index in range(6):
            emit(
                step={
                    'title': '\u6a21\u578b\u89c4\u5212',
                    'detail': f'\u7b2c {round_index + 1} \u8f6e\u51b3\u7b56',
                    'status': PROCESSING_STATUS_RUNNING,
                },
                text='\u6b63\u5728\u8bf7\u6c42\u5927\u6a21\u578b\u89c4\u5212',
            )
            completion = _request_model_completion(provider, {
                'model': provider.default_model,
                'temperature': provider.temperature,
                'max_tokens': provider.max_tokens,
                'messages': messages,
                'tools': tools,
                'tool_choice': 'auto',
            })
            choice = ((completion or {}).get('choices') or [{}])[0]
            message = choice.get('message') or {}
            content = (message.get('content') or '').strip()
            tool_calls = message.get('tool_calls') or []

            if tool_calls:
                emit(
                    step={
                        'title': '\u751f\u6210\u5de5\u5177\u8ba1\u5212',
                        'detail': f'\u672c\u8f6e\u51c6\u5907\u8c03\u7528 {len(tool_calls)} \u4e2a\u5de5\u5177\u3002',
                        'status': PROCESSING_STATUS_COMPLETED,
                    },
                    text=f'\u51c6\u5907\u8c03\u7528 {len(tool_calls)} \u4e2a\u5de5\u5177',
                )
                messages.append({'role': 'assistant', 'content': content or '', 'tool_calls': tool_calls})
                for tool_call in tool_calls:
                    function_payload = tool_call.get('function') or {}
                    tool_name = function_payload.get('name', '')
                    registry_entry = registry.get(tool_name)
                    if not registry_entry:
                        continue
                    arguments = _parse_tool_arguments(function_payload.get('arguments'))
                    emit(
                        tool_event={'name': tool_name, 'detail': '\u5f00\u59cb\u8c03\u7528', 'status': PROCESSING_STATUS_RUNNING},
                        text=f'\u6b63\u5728\u8c03\u7528 {tool_name}',
                    )
                    tool_result = _run_tool_call(session, user_message, user, tool_name, arguments, registry_entry=registry_entry)
                    executed_tool_names.append(tool_name)
                    sections.extend(tool_result.get('sections', []))
                    citations.extend(tool_result.get('citations', []))
                    if tool_result.get('pending_action_draft'):
                        pending_action_draft = tool_result['pending_action_draft']
                    if tool_result.get('message_type') == AIOpsChatMessage.TYPE_ACTION:
                        message_type = AIOpsChatMessage.TYPE_ACTION
                    elif tool_result.get('message_type') == AIOpsChatMessage.TYPE_ANALYSIS and message_type != AIOpsChatMessage.TYPE_ACTION:
                        message_type = AIOpsChatMessage.TYPE_ANALYSIS
                    tool_output = tool_result.get('tool_output') or {}
                    tool_status = PROCESSING_STATUS_FAILED if isinstance(tool_output, dict) and tool_output.get('error') else PROCESSING_STATUS_COMPLETED
                    emit(
                        tool_event={'name': tool_name, 'detail': _summarize_tool_result(tool_result), 'status': tool_status},
                        text=f'{tool_name} \u8c03\u7528\u5b8c\u6210',
                    )
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call.get('id'),
                        'content': json.dumps(tool_result.get('tool_output') or {}, ensure_ascii=False, default=_json_default),
                    })
                continue

            final_content = content
            if not executed_tool_names:
                emit(
                    step={
                        'title': '未命中任何工具',
                        'detail': '模型未调用任何工具，当前策略不允许直接自由回答。',
                        'status': PROCESSING_STATUS_FAILED,
                    },
                    text='模型未命中任何工具',
                )
                return _build_dispatch_error_result(
                    '模型未调用任何工具，请检查当前模型是否支持 tool-calling，或检查 MCP/Skill 配置是否完整。',
                    code='no_tool_called',
                    message='模型未调用任何工具，无法完成问答。',
                )
            emit(
                step={
                    'title': '\u751f\u6210\u56de\u590d',
                    'detail': '\u6a21\u578b\u5df2\u8fd4\u56de\u6700\u7ec8\u56de\u7b54\u3002',
                    'status': PROCESSING_STATUS_COMPLETED,
                },
                text='\u6b63\u5728\u6574\u7406\u56de\u7b54',
            )
            break
    except Exception as exc:
        emit(
            step={
                'title': 'MCP \u5de5\u5177\u94fe\u5f02\u5e38',
                'detail': str(exc)[:120],
                'status': PROCESSING_STATUS_FAILED,
            },
            text='模型或工具调用失败',
        )
        return _build_dispatch_error_result(
            str(exc),
            code='runtime_error',
            message='模型或工具调用失败，请检查模型与 MCP 配置。',
        )
    finally:
        for client in managed_clients:
            try:
                client.close()
            except Exception:
                pass

    citations = _dedupe_citations(citations)
    if not final_content:
        intro = '\u5df2\u901a\u8fc7\u5df2\u542f\u7528\u7684 MCP \u4e0e Skills \u83b7\u53d6\u5e73\u53f0\u5185\u80fd\u529b\u7ed3\u679c\u3002'
        if pending_action_draft:
            intro = '\u5df2\u751f\u6210\u4efb\u52a1\u8349\u7a3f\uff0c\u786e\u8ba4\u540e\u5c06\u8c03\u7528\u73b0\u6709\u4efb\u52a1\u4e2d\u5fc3\u6267\u884c\u3002'
        final_content = build_markdown_answer('\u667a\u80fd\u52a9\u624b\u56de\u590d', sections, citations, intro=intro)

    return {
        'content': final_content,
        'citations': citations,
        'tool_calls': executed_tool_names,
        'message_type': message_type,
        'pending_action_draft': pending_action_draft,
        'metadata': {'execution_mode': 'mcp_skills'},
    }


def _build_chat_result(session, user_message, user, question, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    emit(
        status_value=PROCESSING_STATUS_RUNNING,
        text='\u6b63\u5728\u5206\u6790\u4f60\u7684\u95ee\u9898',
        step={'title': '\u63a5\u6536\u95ee\u9898', 'detail': (question or '')[:120], 'status': PROCESSING_STATUS_COMPLETED},
    )
    try:
        result = _dispatch_with_tool_runtime(session, user_message, user, question, progress_callback=emit)
        if result:
            return result
    except Exception as exc:
        emit(
            step={'title': '\u5904\u7406\u5f02\u5e38', 'detail': str(exc)[:120], 'status': PROCESSING_STATUS_FAILED},
            text='\u95ee\u7b54\u5931\u8d25',
        )
        return _build_dispatch_error_result(str(exc))
    return _build_dispatch_error_result('\u672a\u83b7\u5f97\u5230\u6709\u6548\u56de\u7b54')



def _stream_dispatch_result(message_id, payload, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    final_content = payload.get('content') or ''
    message_type = payload.get('message_type') or AIOpsChatMessage.TYPE_TEXT
    citations = payload.get('citations') or []
    tool_calls = payload.get('tool_calls') or []
    metadata_updates = dict(payload.get('metadata') or {})

    emit(
        status_value=PROCESSING_STATUS_STREAMING,
        text='\u6b63\u5728\u8f93\u51fa\u56de\u590d',
        step={'title': '\u8f93\u51fa\u56de\u590d', 'detail': '\u6b63\u5728\u5c06\u7ed3\u679c\u6d41\u5f0f\u8fd4\u56de\u5230\u524d\u7aef\u3002', 'status': PROCESSING_STATUS_RUNNING},
    )

    if not final_content:
        _update_chat_message_processing(
            message_id,
            status_value=PROCESSING_STATUS_COMPLETED,
            text='\u5206\u6790\u5b8c\u6210',
            content=final_content,
            message_type=message_type,
            citations=citations,
            tool_calls=tool_calls,
            metadata_updates=metadata_updates,
        )
        return

    frame_count = min(10, max(3, (len(final_content) + 119) // 120))
    chunk_size = max(1, (len(final_content) + frame_count - 1) // frame_count)
    for cursor in range(chunk_size, len(final_content), chunk_size):
        _update_chat_message_processing(
            message_id,
            status_value=PROCESSING_STATUS_STREAMING,
            text='\u6b63\u5728\u8f93\u51fa\u56de\u590d',
            content=final_content[:cursor],
            message_type=message_type,
            metadata_updates=metadata_updates,
        )
        time.sleep(0.08)

    _update_chat_message_processing(
        message_id,
        status_value=PROCESSING_STATUS_COMPLETED,
        text='\u5206\u6790\u5b8c\u6210',
        content=final_content,
        message_type=message_type,
        citations=citations,
        tool_calls=tool_calls,
        metadata_updates=metadata_updates,
    )



def _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=False, progress_callback=None, question=''):
    config = get_agent_config()
    assistant_message.refresh_from_db()
    final_content = result.get('content', '')
    merged_metadata = {**(assistant_message.metadata or {}), **(result.get('metadata') or {})}
    pending_action = None
    draft = result.get('pending_action_draft')

    if draft and not draft.get('error'):
        if not config.allow_action_execution:
            merged_metadata['action_execution_disabled'] = True
        else:
            pending_action = create_pending_task_action_from_draft(session, assistant_message, draft)
            merged_metadata['pending_action_id'] = pending_action.id
            if not config.require_confirmation and user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
                try:
                    task = confirm_action(pending_action, user)
                    pending_action.refresh_from_db()
                    final_content = f"{final_content}\n\n\u5df2\u6839\u636e\u5f53\u524d\u914d\u7f6e\u81ea\u52a8\u6267\u884c\u4efb\u52a1\uff1a{task.name}\uff08#{task.id}\uff09\u3002"
                except ValueError:
                    pending_action.refresh_from_db()

    payload = {
        'content': final_content,
        'message_type': result.get('message_type') or AIOpsChatMessage.TYPE_TEXT,
        'citations': result.get('citations') or [],
        'tool_calls': result.get('tool_calls') or [],
        'metadata': {**merged_metadata, 'processing_status': PROCESSING_STATUS_COMPLETED, 'processing_text': '\u5206\u6790\u5b8c\u6210'},
    }

    if enable_stream:
        _stream_dispatch_result(assistant_message.id, payload, progress_callback=progress_callback)
    else:
        assistant_message.message_type = payload['message_type']
        assistant_message.content = payload['content']
        assistant_message.citations = payload['citations']
        assistant_message.tool_calls = payload['tool_calls']
        assistant_message.metadata = payload['metadata']
        assistant_message.save(update_fields=['message_type', 'content', 'citations', 'tool_calls', 'metadata'])

    _touch_chat_session(session, question=question or payload['content'] or session.title)
    return assistant_message, pending_action



def _run_async_chat_worker(session_id, user_message_id, user_id, assistant_message_id, question):
    close_old_connections()
    try:
        session = AIOpsChatSession.objects.select_related('user').get(pk=session_id)
        user_message = AIOpsChatMessage.objects.get(pk=user_message_id)
        assistant_message = AIOpsChatMessage.objects.get(pk=assistant_message_id)
        user = session.user if session.user_id == user_id else session.user.__class__.objects.get(pk=user_id)
        emit = _make_processing_callback(assistant_message_id)
        result = _build_chat_result(session, user_message, user, question, progress_callback=emit)
        _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=True, progress_callback=emit, question=question)
    except Exception as exc:
        _update_chat_message_processing(
            assistant_message_id,
            status_value=PROCESSING_STATUS_FAILED,
            text='\u95ee\u7b54\u5931\u8d25',
            step={'title': '\u5904\u7406\u5931\u8d25', 'detail': str(exc)[:120], 'status': PROCESSING_STATUS_FAILED},
            content=f'\u95ee\u7b54\u5931\u8d25\uff1a{str(exc)}',
            message_type=AIOpsChatMessage.TYPE_ERROR,
            metadata_updates={'execution_mode': 'error', 'error_detail': str(exc)[:500]},
        )
        session = AIOpsChatSession.objects.filter(pk=session_id).first()
        if session:
            _touch_chat_session(session, question=question)
    finally:
        close_old_connections()



def start_async_chat_processing(session, user_message, user, assistant_message):
    worker = threading.Thread(
        target=_run_async_chat_worker,
        kwargs={
            'session_id': session.id,
            'user_message_id': user_message.id,
            'user_id': user.id,
            'assistant_message_id': assistant_message.id,
            'question': user_message.content,
        },
        daemon=True,
        name=f'aiops-chat-{assistant_message.id}',
    )
    worker.start()
    return worker



def dispatch_chat(session, user_message, user, question):
    result = _build_chat_result(session, user_message, user, question)
    assistant_message = AIOpsChatMessage.objects.create(
        session=session,
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        message_type=AIOpsChatMessage.TYPE_TEXT,
        content='',
        citations=[],
        tool_calls=[],
        metadata={},
    )
    return _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=False, question=question)


def build_audit_overview():
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        'sessions_today': AIOpsChatSession.objects.filter(created_at__gte=today_start).count(),
        'messages_today': AIOpsChatMessage.objects.filter(created_at__gte=today_start).count(),
        'actions_today': AIOpsPendingAction.objects.filter(created_at__gte=today_start).count(),
        'failed_actions_today': AIOpsPendingAction.objects.filter(created_at__gte=today_start, status=AIOpsPendingAction.STATUS_FAILED).count(),
        'providers_total': AIOpsModelProvider.objects.count(),
        'mcp_total': AIOpsMCPServer.objects.filter(is_enabled=True).count(),
    }
