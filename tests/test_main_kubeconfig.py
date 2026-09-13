"""
tests/test_main_kubeconfig.py
Tests for api/main.py's _write_kubeconfig_from_env -- writes KUBECONFIG_YAML
env content to a file and points KUBECONFIG at it, since Railway can't
mount an arbitrary file into the container and kubectl (used by
agents/agent_08_drift_detection/tools.py) only reads config from a file path.
"""

import os
from unittest.mock import patch

from api.main import _write_kubeconfig_from_env


class TestWriteKubeconfigFromEnv:
    def test_noop_when_kubeconfig_yaml_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KUBECONFIG_YAML", None)
            os.environ.pop("KUBECONFIG", None)
            _write_kubeconfig_from_env()
            assert "KUBECONFIG" not in os.environ

    def test_writes_file_and_sets_kubeconfig_env_var(self, tmp_path):
        fake_yaml = "apiVersion: v1\nkind: Config\nclusters: []\n"
        with patch.dict(os.environ, {"KUBECONFIG_YAML": fake_yaml}):
            os.environ.pop("KUBECONFIG", None)
            _write_kubeconfig_from_env()
            try:
                assert os.environ["KUBECONFIG"] == "/tmp/kubeconfig"
                with open("/tmp/kubeconfig") as f:
                    assert f.read() == fake_yaml
            finally:
                os.remove("/tmp/kubeconfig")
                os.environ.pop("KUBECONFIG", None)
