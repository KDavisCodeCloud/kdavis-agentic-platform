"""
tests/mocks/azure_fixtures.py
Drop-in mock Azure data for local testing of Cloud Decoded agents.

These constants represent realistic Azure DevOps build events, AKS pod crash
logs, kubectl describe output, and Activity Log entries that agents would
receive in production.

Usage:
    from tests.mocks.azure_fixtures import MOCK_AKS_CRASH_LOG, MOCK_KUBECTL_DESCRIBE
"""

# ── AKS pod crash log ─────────────────────────────────────────────────────────

MOCK_AKS_CRASH_LOG = """\
2026-06-23T01:52:11Z payment-service-7d9f8b-xkq2p  Back-off restarting failed container
2026-06-23T01:52:11Z payment-service-7d9f8b-xkq2p  OOMKilled
2026-06-23T01:51:44Z payment-service-7d9f8b-xkq2p  Started container payment-service
2026-06-23T01:51:40Z payment-service-7d9f8b-xkq2p  Pulling image "acr.azurecr.io/payment-service:v2.4.1"
2026-06-23T01:51:38Z default-scheduler              Successfully assigned production/payment-service-7d9f8b-xkq2p to aks-nodepool-01
2026-06-23T01:50:12Z payment-service-7d9f8b-xkq2p  Back-off restarting failed container
2026-06-23T01:50:12Z payment-service-7d9f8b-xkq2p  OOMKilled
"""

# ── kubectl describe pod output ───────────────────────────────────────────────

MOCK_KUBECTL_DESCRIBE = {
    "metadata": {
        "name": "payment-service-7d9f8b-xkq2p",
        "namespace": "production",
        "labels": {"app": "payment-service", "version": "v2.4.1"},
    },
    "status": {
        "phase": "Running",
        "containerStatuses": [
            {
                "name": "payment-service",
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                "lastState": {
                    "terminated": {
                        "exitCode": 137,
                        "reason": "OOMKilled",
                        "finishedAt": "2026-06-23T01:52:09Z",
                    }
                },
                "restartCount": 4,
                "image": "acr.azurecr.io/payment-service:v2.4.1",
                "ready": False,
            }
        ],
    },
    "spec": {
        "containers": [
            {
                "name": "payment-service",
                "resources": {
                    "limits": {"memory": "512Mi", "cpu": "500m"},
                    "requests": {"memory": "256Mi", "cpu": "250m"},
                },
            }
        ]
    },
}

# ── Azure DevOps build failure webhook payload ────────────────────────────────

MOCK_AZURE_DEVOPS_WEBHOOK_FAILURE = {
    "eventType": "build.complete",
    "resource": {
        "id": 555,
        "result": "failed",
        "definition": {"id": 7, "name": "Deploy to Staging"},
        "sourceBranch": "refs/heads/main",
        "sourceVersion": "a1b2c3d4e5f6",
        "repository": {"id": "repo-abc-123", "name": "BackendServices"},
        "finishTime": "2026-06-23T01:52:11Z",
    },
    "resourceContainers": {
        "account": {"id": "contoso"},
        "project": {"name": "BackendServices"},
    },
}

# ── Azure Monitor Activity Log — failed K8s operation ────────────────────────

MOCK_AZURE_ACTIVITY_LOG = {
    "value": [
        {
            "eventTimestamp": "2026-06-23T01:52:00Z",
            "operationName": {
                "value": "Microsoft.ContainerService/managedClusters/pods/read",
                "localizedValue": "List or Get pods",
            },
            "status": {"value": "Failed", "localizedValue": "Failed"},
            "resourceId": (
                "/subscriptions/00000000-0000-0000-0000-000000000000"
                "/resourceGroups/prod-rg"
                "/providers/Microsoft.ContainerService/managedClusters/prod-aks"
            ),
            "caller": "system",
            "level": "Error",
        }
    ]
}

# ── Prometheus AlertManager webhook ───────────────────────────────────────────

MOCK_PROMETHEUS_ALERTMANAGER = {
    "version": "4",
    "groupKey": '{}:{alertname="KubePodCrashLooping"}',
    "status": "firing",
    "receiver": "cloud-decoded-webhook",
    "groupLabels": {"alertname": "KubePodCrashLooping"},
    "commonLabels": {
        "alertname": "KubePodCrashLooping",
        "namespace": "production",
        "cluster": "prod-aks",
    },
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "KubePodCrashLooping",
                "namespace": "production",
                "pod": "payment-service-7d9f8b-xkq2p",
                "container": "payment-service",
                "reason": "OOMKilled",
                "cluster": "prod-aks",
            },
            "annotations": {
                "description": (
                    "Pod payment-service-7d9f8b-xkq2p/payment-service has been "
                    "restarting 4 times / 10 minutes."
                ),
                "runbook_url": "https://runbooks.prometheus-operator.dev/runbooks/kubernetes/kubepodcrashlooping",
                "summary": "Pod is crash looping.",
            },
            "startsAt": "2026-06-24T01:52:11Z",
        }
    ],
}

# ── Azure Monitor Common Alert Schema — AKS OOMKilled ────────────────────────

MOCK_AZURE_MONITOR_AKS_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertId": "/subscriptions/00000000/alerts/abc123",
            "alertRule": "K8s CrashLoopBackOff — production",
            "severity": "Sev1",
            "signalType": "Log",
            "monitorCondition": "Fired",
            "monitoringService": "Log Alerts V2",
            "affectedConfigurationItems": [
                "/subscriptions/00000000/resourceGroups/prod-rg"
                "/providers/Microsoft.ContainerService/managedClusters/prod-aks"
            ],
            "firedDateTime": "2026-06-24T01:52:11Z",
        },
        "alertContext": {
            "SearchQuery": "ContainerLog | where Reason == 'OOMKilled'",
            "SearchResults": {
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [
                            {"name": "PodName", "type": "string"},
                            {"name": "Namespace", "type": "string"},
                            {"name": "Reason", "type": "string"},
                            {"name": "ExitCode", "type": "int"},
                            {"name": "RestartCount", "type": "int"},
                        ],
                        "rows": [
                            ["payment-service-7d9f8b-xkq2p", "production", "OOMKilled", 137, 4]
                        ],
                    }
                ]
            },
        },
        "customProperties": {
            "cluster_name": "prod-aks",
            "resource_group": "prod-rg",
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "deployment_name": "payment-service",
            "namespace": "production",
        },
    },
}
