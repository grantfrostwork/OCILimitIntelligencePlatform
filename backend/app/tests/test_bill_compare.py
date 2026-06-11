from pathlib import Path

from openpyxl import Workbook

from app.services.bill_compare import (
    BillComparisonAnalyzer,
    BillComparisonLine,
    LimitCatalog,
    LimitDefinition,
    LimitService,
    load_bill_comparison_lines,
)


def catalog() -> LimitCatalog:
    return LimitCatalog(
        services=[
            LimitService("compute", "Compute"),
            LimitService("block-storage", "Block Volume"),
            LimitService("object-storage", "Object Storage"),
            LimitService("load-balancer", "LbaaS"),
            LimitService("network-load-balancer-api", "Network Load Balancer"),
            LimitService("postgresql", "PostgreSQL"),
            LimitService("vcn", "Virtual Cloud Network"),
        ],
        definitions=[
            LimitDefinition("compute", "standard3-core-count", "Cores for Standard3"),
            LimitDefinition("compute", "standard3-memory-count", "Memory for Standard3"),
            LimitDefinition("compute", "gpu-a10-count", "GPUs for GPU.A10"),
            LimitDefinition("block-storage", "total-storage-gb", "Volume Size (GB)"),
            LimitDefinition("object-storage", "storage-bytes", "Storage capacity (bytes)"),
            LimitDefinition("load-balancer", "lb-flexible-count", "Flexible Load Balancer Count"),
            LimitDefinition(
                "network-load-balancer-api",
                "max-nlb-flexible-count",
                "Flexible Network Load Balancer Count",
            ),
            LimitDefinition("postgresql", "dbsystem-e6-count", "Postgresql Dbsystem E6 Count"),
            LimitDefinition("vcn", "reserved-public-ip-count", "Reserved Public IP Count"),
        ],
    )


def line(**overrides) -> BillComparisonLine:
    defaults = dict(
        row_number=2,
        source_sheet="AWS_CSV_Output",
        aws_product="Amazon Elastic Compute Cloud",
        aws_description="$0.40 per On Demand Linux c5.xlarge Instance Hour",
        quantity=744.0,
        aws_cost=0.0,
        aws_vcpu=4.0,
        aws_memory_gib=8.0,
        aws_nvme_tb=0.0,
        aws_nvme_gb=0.0,
        aws_gpu=0.0,
        oci_service_name="VM.Standard3.Flex",
        oci_compute_shape="OCI Compute - Intel X9-2 Virtual Compute [On-Demand Instances]",
        oci_part_num_compute_shape="B93311",
        oci_part_num_memory="B93312",
        oci_part_num_obj_stor="",
        oci_part_num_block_vol="",
        oci_part_num_block_vol_perf="",
        oci_datatransfer_part_num="",
        oci_sku="",
        oci_sku2="",
    )
    defaults.update(overrides)
    return BillComparisonLine(**defaults)


def test_maps_compute_hours_to_ocpu_and_memory_limits():
    result = BillComparisonAnalyzer(catalog()).analyze_lines([line()])
    by_metric = {item["metric"]: item for item in result["requirements"]}

    assert by_metric["compute_ocpu"]["service_name"] == "compute"
    assert by_metric["compute_ocpu"]["limit_name"] == "standard3-core-count"
    assert by_metric["compute_ocpu"]["required_quantity"] == 2.0
    assert by_metric["compute_memory"]["limit_name"] == "standard3-memory-count"
    assert by_metric["compute_memory"]["required_quantity"] == 8.0


def test_maps_storage_and_load_balancer_rows():
    rows = [
        line(
            row_number=3,
            aws_product="Amazon Elastic Compute Cloud",
            aws_description="$0.1047 per GB-month of General Purpose (gp3) provisioned storage",
            quantity=100.0,
            aws_vcpu=0.0,
            aws_memory_gib=0.0,
            oci_service_name="OCI Block Volume Storage",
            oci_compute_shape="",
            oci_part_num_block_vol="B91961",
        ),
        line(
            row_number=4,
            aws_product="Elastic Load Balancing",
            aws_description="$0.0277 per Application LoadBalancer-hour (or partial hour)",
            quantity=1488.0,
            aws_vcpu=0.0,
            aws_memory_gib=0.0,
            oci_service_name="OCI - Load Balancer Base / Load Balancer Bandwidth",
            oci_compute_shape="",
            oci_sku="B93030",
        ),
    ]
    result = BillComparisonAnalyzer(catalog()).analyze_lines(rows)
    by_metric = {item["metric"]: item for item in result["requirements"]}

    assert by_metric["block_volume_storage"]["limit_name"] == "total-storage-gb"
    assert by_metric["block_volume_storage"]["required_quantity"] == 100.0
    assert by_metric["load_balancer_count"]["limit_name"] == "lb-flexible-count"
    assert by_metric["load_balancer_count"]["required_quantity"] == 2.0


def test_loads_aws_csv_output_sheet(tmp_path: Path):
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
            "oci_windows_os_part_#",
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
            0,
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
    path = tmp_path / "bill.xlsx"
    workbook.save(path)

    rows = load_bill_comparison_lines(path)

    assert len(rows) == 1
    assert rows[0].aws_product == "Amazon Elastic Compute Cloud"
    assert rows[0].aws_vcpu == 4.0
