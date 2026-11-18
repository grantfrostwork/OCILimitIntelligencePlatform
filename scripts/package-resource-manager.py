#!/usr/bin/env python3
"""Build a deterministic, allowlisted Resource Manager ZIP without local state/secrets."""
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/terraform/resource-manager"
FILES = (
    "versions.tf", "variables.tf", "main.tf", "network.tf", "compute.tf",
    "load_balancer.tf", "bastion.tf", "outputs.tf", ".terraform.lock.hcl",
    "schema.yaml", "cloud-init.yaml.tftpl", "bootstrap.py", "install.sh",
    "ready.sh", "oci-lip.service", "README.md", "VALIDATION.md", "terraform.tfvars.example",
    "oidc-secret.example.json",
)


def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/oci-lip-resource-manager.zip").resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(FILES):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (SOURCE / name).read_bytes())
    print(destination)


if __name__ == "__main__":
    main()
