#!/usr/bin/env bash
set -euo pipefail
# Public source/config mounts must remain readable by non-root Prometheus/Grafana.
# bootstrap.py applies umask 077 and mode 600 to all secret files.
umask 022
# No shell tracing: credentials must never enter cloud-init or journal output.
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
python3 -m venv /opt/oci-lip-bootstrap
/opt/oci-lip-bootstrap/bin/pip install 'oci==2.168.1'
if [[ ! -d /opt/oci-lip/.git ]]; then
  git clone https://github.com/grantfrostwork/OCILimitIntelligencePlatform.git /opt/oci-lip
fi
commit=$(python3 -c 'import json; print(json.load(open("/etc/oci-lip/config.json"))["commit"])')
git -C /opt/oci-lip checkout --detach "$commit"
# Abort before starting containers if the Vault secret or OIDC configuration is invalid.
/opt/oci-lip-bootstrap/bin/python /usr/local/lib/oci-lip/bootstrap.py
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http
  firewall-cmd --reload
fi
systemctl daemon-reload
systemctl enable --now oci-lip.service
