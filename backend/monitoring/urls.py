from django.urls import path

from monitoring import api

urlpatterns = [
    path('hosts/probe/', api.HostProbeBulkView.as_view(), name='monitoring-hosts-probe-bulk'),
    path('hosts/<int:host_id>/probe/', api.HostProbeSingleView.as_view(), name='monitoring-hosts-probe-single'),
    path('databases/probe/', api.DatabaseProbeBulkView.as_view(), name='monitoring-databases-probe-bulk'),
    path('databases/<int:ds_id>/probe/', api.DatabaseProbeSingleView.as_view(), name='monitoring-databases-probe-single'),
]
