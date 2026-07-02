from app.services.oci_sdk import OciSdkTelemetry


class ThrottledError(Exception):
    status = 429


def test_sdk_telemetry_tracks_retries_throttles_and_wait_time():
    telemetry = OciSdkTelemetry()
    telemetry.record_request(0.25)
    telemetry.record_retry(ThrottledError(), 2.5)
    telemetry.record_final_error(ThrottledError())

    snapshot = telemetry.snapshot()

    assert snapshot["api_request_count"] == 1
    assert snapshot["api_retry_count"] == 1
    assert snapshot["api_throttle_count"] == 2
    assert snapshot["api_concurrency_wait_seconds"] == 0.25
    assert snapshot["api_retry_sleep_seconds"] == 2.5
