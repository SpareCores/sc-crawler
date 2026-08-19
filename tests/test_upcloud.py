from unittest.mock import Mock, patch

from sc_crawler.table_fields import Status
from sc_crawler.vendors._upcloud import _upcloud_server_status


def test_upcloud_server_status_from_current_offering():
    vendor = Mock(regions=[])
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "HIMEM-2xCPU-16GB",
                "family": "general_purpose",
                "current_offering": "no",
            },
        )
        == Status.RETIRED
    )
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "PREMIUM-2xCPU-4GB",
                "family": "premium",
                "current_offering": "yes",
            },
        )
        == Status.ACTIVE
    )


def test_upcloud_server_status_gpu_stock():
    vendor = Mock(regions=[Mock(region_id="de-fra1")])
    server = {
        "name": "GPU-8xCPU-64GB-1xL40S",
        "family": "gpu",
        "current_offering": "yes",
    }
    with patch(
        "sc_crawler.vendors._upcloud._get_gpu_region_availability",
        return_value={"GPU-8xCPU-64GB-1xL40S": {"amount": 2}},
    ):
        assert _upcloud_server_status(vendor, server) == Status.ACTIVE
    with patch(
        "sc_crawler.vendors._upcloud._get_gpu_region_availability",
        return_value={"GPU-8xCPU-64GB-1xL40S": {"amount": 0}},
    ):
        assert _upcloud_server_status(vendor, server) == Status.INACTIVE


def test_upcloud_server_status_gpu_without_regions_is_inactive():
    vendor = Mock(regions=[])
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "GPU-8xCPU-64GB-1xL40S",
                "family": "gpu",
                "current_offering": "yes",
            },
        )
        == Status.INACTIVE
    )
