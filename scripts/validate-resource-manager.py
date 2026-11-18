#!/usr/bin/env python3
"""Validate schema, bootstrap payload and artifact layout without creating OCI resources.

Requires: PyYAML, jsonschema, python-hcl2, Terraform on PATH.
Oracle's published meta-schema is downloaded over verified HTTPS.
"""
import base64
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile
import hcl2
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "deploy/terraform/resource-manager"
TERRAFORM = os.environ.get("TERRAFORM", "terraform")
DOC = "https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/terraformconfigresourcemanager_topic-schema.htm"


class Blocks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.inside = True
            self.blocks.append("")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.blocks[-1] += data


def main():
    schema = yaml.safe_load((STACK / "schema.yaml").read_text())
    parser = Blocks()
    with urlopen(DOC, timeout=60) as response:
        parser.feed(response.read().decode())
    meta = yaml.safe_load(next(b for b in parser.blocks if "# Meta JSON Schema." in b).strip("` \n"))
    jsonschema.Draft7Validator(meta).validate(schema)
    with (STACK / "variables.tf").open() as stream:
        variables = {key.strip('"'): value for item in hcl2.load(stream)["variable"] for key, value in item.items()}
    assert set(variables) == set(schema["variables"]), "ORM schema must cover all Terraform variables"
    grouped = [v for g in schema["variableGroups"] for v in g["variables"]]
    assert len(grouped) == len(set(grouped)) and set(grouped) == set(variables)
    print("Oracle ORM schema and variable coverage: PASS")

    args = {"config": base64.b64encode(b'{"fixture":true}').decode()}
    for key, filename in {"bootstrap": "bootstrap.py", "install": "install.sh", "service": "oci-lip.service", "ready": "ready.sh"}.items():
        args[key] = base64.b64encode((STACK / filename).read_bytes()).decode()
    expression = 'templatefile("cloud-init.yaml.tftpl", ' + json.dumps(args) + ')\n'
    result = subprocess.run([TERRAFORM, "console"], cwd=STACK, input=expression, text=True, capture_output=True, check=True)
    rendered = json.loads(result.stdout) if result.stdout.startswith('"') else None
    # Terraform uses a heredoc representation for multiline strings.
    if rendered is None:
        match = re.fullmatch(r'<<-?(\w+)\n(.*)\n\1\n?', result.stdout, re.DOTALL)
        assert match, "Unexpected Terraform console rendering"
        rendered = match.group(2) + "\n"
    payload = yaml.safe_load(rendered)
    assert len(rendered.encode()) < 32768, "Keep decoded OCI user data below 32 KiB"
    files = {entry["path"]: entry for entry in payload["write_files"]}
    for path, key in {"/usr/local/lib/oci-lip/bootstrap.py": "bootstrap", "/usr/local/sbin/oci-lip-install": "install", "/usr/local/sbin/oci-lip-ready": "ready", "/etc/systemd/system/oci-lip.service": "service"}.items():
        assert files[path]["content"] == args[key]
        base64.b64decode(files[path]["content"], validate=True)
    assert files['/etc/oci-lip/config.json']['permissions'] == '0600'
    print(f"Terraform-rendered cloud-init and embedded assets: PASS ({len(rendered.encode())} bytes)")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "stack.zip"
        subprocess.run(["python3", str(ROOT / "scripts/package-resource-manager.py"), str(archive)], check=True, capture_output=True)
        with ZipFile(archive) as package:
            names = package.namelist()
            assert "schema.yaml" in names and "versions.tf" in names
            assert all('/' not in n and not n.endswith(('.tfstate', '.tfplan')) and n != '.env' for n in names)
            for name in names:
                assert package.read(name) == (STACK / name).read_bytes()
        print("Self-contained allowlisted ZIP: PASS")


if __name__ == "__main__":
    main()
