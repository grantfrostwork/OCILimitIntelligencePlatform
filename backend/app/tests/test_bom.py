from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import BomRecommendation, LimitItem
from app.services.bom import BomAnalyzer
from app.services.collector import _is_dynamic_compute_limit_value


def test_extracts_and_merges_resource_quantities():
    analyzer = BomAnalyzer(db=None, settings=None)  # type: ignore[arg-type]
    resources = analyzer.extract_resources(
        "Deploy 3 load balancers, 2 load balancers, 4 subnets, and 10 OCPUs."
    )
    by_type = {item.resource_type: item for item in resources}

    assert by_type["load_balancer"].quantity == 5
    assert by_type["subnet"].quantity == 4
    assert by_type["ocpus"].quantity == 10


def test_extracts_terraform_resource_counts():
    analyzer = BomAnalyzer(db=None, settings=None)  # type: ignore[arg-type]
    resources = analyzer.extract_resources(
        """
        resource "oci_core_instance" "a" {}
        resource "oci_core_instance" "b" {}
        resource "oci_core_nat_gateway" "nat" {}
        """
    )
    by_type = {item.resource_type: item for item in resources}

    assert by_type["compute_instances"].quantity == 2
    assert by_type["nat_gateway"].quantity == 1


def test_bill_comparison_upload_uses_live_limit_data(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add_all(
        [
            LimitItem(
                region="us-ashburn-1",
                compartment_ocid="tenancy",
                service_name="compute",
                limit_name="standard3-core-count",
                resource_name="standard3-core-count",
                scope_type="AD",
                availability_domain="AD-1",
                subscription_id="",
                last_allowed_limit=10,
                last_used=8,
                last_available=2,
                last_percent_used=80,
                last_collection_status="ok",
            ),
            LimitItem(
                region="us-ashburn-1",
                compartment_ocid="tenancy",
                service_name="compute",
                limit_name="standard3-memory-count",
                resource_name="standard3-memory-count",
                scope_type="AD",
                availability_domain="AD-1",
                subscription_id="",
                last_allowed_limit=16,
                last_used=8,
                last_available=8,
                last_percent_used=50,
                last_collection_status="ok",
            ),
        ]
    )
    db.commit()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "AWS_CSV_Output"
    sheet.append(
        [
            "aws_product_name1_x",
            "aws_item_description",
            "aws_product_quantity",
            "aws_cost",
            "aws_vcpu",
            "aws_memory_gib",
            "aws_NVMe_TB",
            "aws_NVMe_GB",
            "aws_gpu",
            "oci_part_num_compute_shape",
            "oci_part_num_memory",
            "oci_compute_shape",
            "oci_service_name",
            "oci_part_num_obj_stor",
            "oci_part_num_block_vol",
            "oci_part_num_block_vol_perf",
            "oci_datatransfer_part_num",
            "oci_sku",
            "oci_sku2",
        ]
    )
    sheet.append(
        [
            "Amazon Elastic Compute Cloud",
            "$0.228 per On Demand Linux c5.xlarge Instance Hour",
            744,
            0,
            4,
            8,
            0,
            0,
            0,
            "B93311",
            "B93312",
            "OCI Compute - Intel X9-2 Virtual Compute [On-Demand Instances]",
            "VM.Standard3.Flex",
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)

    settings = Settings(upload_dir=tmp_path)
    BomAnalyzer(db, settings).analyze_upload(
        filename="bill.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file=payload,
    )
    recommendations = list(db.scalars(select(BomRecommendation)))
    by_limit = {item.matching_limit_name: item for item in recommendations if item.matching_limit_name}

    assert by_limit["standard3-core-count"].limit_increase_needed is True
    assert by_limit["standard3-core-count"].recommended_new_limit == 12.5
    assert by_limit["standard3-memory-count"].limit_increase_needed is True


def test_compute_dynamic_limit_values_are_ignored():
    assert _is_dynamic_compute_limit_value("compute", {"value": " Dynamic "}) is True
    assert _is_dynamic_compute_limit_value("block-storage", {"value": "Dynamic"}) is False
