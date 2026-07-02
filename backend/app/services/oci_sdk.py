from __future__ import annotations

import time
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

import oci
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.exceptions import BaseRequestException, ClientError, ServiceError
from oci.identity import IdentityClient
from oci.limits import LimitsClient
from oci.ons import NotificationControlPlaneClient, NotificationDataPlaneClient
from oci.ons.models import CreateSubscriptionDetails, CreateTopicDetails, MessageDetails
from oci.retry import retry_sleep_utils

from app.core.config import Settings


ClientT = TypeVar("ClientT")


_limiter_lock = threading.Lock()
_global_limiters: dict[int, threading.BoundedSemaphore] = {}


def _global_limiter(limit: int) -> threading.BoundedSemaphore:
    normalized = max(1, limit)
    with _limiter_lock:
        return _global_limiters.setdefault(normalized, threading.BoundedSemaphore(normalized))


class OciSdkTelemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local = threading.local()
        self._requests = 0
        self._retries = 0
        self._throttles = 0
        self._concurrency_wait_seconds = 0.0
        self._retry_sleep_seconds = 0.0

    @contextmanager
    def operation(self, region: str, operation: str) -> Iterator[None]:
        previous = getattr(self._local, "operation", None)
        self._local.operation = (region, operation)
        try:
            yield
        finally:
            self._local.operation = previous

    def record_request(self, concurrency_wait_seconds: float) -> None:
        with self._lock:
            self._requests += 1
            self._concurrency_wait_seconds += concurrency_wait_seconds

    def record_retry(self, exception: Exception, sleep_seconds: float) -> None:
        with self._lock:
            self._retries += 1
            self._retry_sleep_seconds += sleep_seconds
            if getattr(exception, "status", None) == 429:
                self._throttles += 1

    def record_final_error(self, exception: Exception) -> None:
        if getattr(exception, "status", None) != 429:
            return
        with self._lock:
            self._throttles += 1

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "api_request_count": self._requests,
                "api_retry_count": self._retries,
                "api_throttle_count": self._throttles,
                "api_concurrency_wait_seconds": self._concurrency_wait_seconds,
                "api_retry_sleep_seconds": self._retry_sleep_seconds,
            }


class _ObservedRetryStrategy(oci.retry.ExponentialBackOffWithDecorrelatedJitterRetryStrategy):
    def __init__(self, telemetry: OciSdkTelemetry) -> None:
        default = oci.retry.DEFAULT_RETRY_STRATEGY
        super().__init__(
            default.base_sleep_time_seconds,
            default.exponent_growth_factor,
            default.max_wait_between_calls_seconds,
            default.checkers,
            decorrelated_jitter=default.decorrelated_jitter,
        )
        self._telemetry = telemetry

    def do_sleep(self, attempt, exception) -> None:
        sleep_seconds = (
            retry_sleep_utils.get_exponential_backoff_with_decorrelated_jitter_sleep_time(
                self.base_sleep_time_seconds,
                self.exponent_growth_factor,
                self.max_wait_between_calls_seconds,
                attempt,
                self.decorrelated_jitter,
            )
        )
        self._telemetry.record_retry(exception, sleep_seconds)
        time.sleep(sleep_seconds)


class OciSdkError(RuntimeError):
    def __init__(
        self,
        operation: str,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        opc_request_id: str | None = None,
    ) -> None:
        self.operation = operation
        self.status = status
        self.code = code
        self.opc_request_id = opc_request_id
        detail = f"{operation} failed"
        if status is not None:
            detail += f" ({status}"
            if code:
                detail += f" {code}"
            detail += ")"
        detail += f": {message}"
        if opc_request_id:
            detail += f" [opc-request-id: {opc_request_id}]"
        super().__init__(detail)


class OciSdk:
    """Thread-safe OCI SDK gateway with one client pool per worker thread and region."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telemetry = OciSdkTelemetry()
        self._local = threading.local()
        self._auth_lock = threading.Lock()
        self._profile_config: dict[str, Any] | None = None
        self._signer: InstancePrincipalsSecurityTokenSigner | None = None
        self._retry_strategy = _ObservedRetryStrategy(self.telemetry)
        self._request_limiter = _global_limiter(settings.oci_global_max_concurrent_requests)

    def list_region_subscriptions(
        self, tenancy_id: str, *, region: str
    ) -> list[Any]:
        client = self._client(IdentityClient, region)
        return self._all(
            "identity.list_region_subscriptions",
            region,
            client.list_region_subscriptions,
            tenancy_id,
        )

    def list_services(self, compartment_id: str, *, region: str) -> list[Any]:
        client = self._client(LimitsClient, region)
        return self._all("limits.list_services", region, client.list_services, compartment_id)

    def list_limit_values(
        self, compartment_id: str, service_name: str, *, region: str
    ) -> list[Any]:
        client = self._client(LimitsClient, region)
        return self._all(
            "limits.list_limit_values",
            region,
            client.list_limit_values,
            compartment_id,
            service_name,
        )

    def list_limit_definitions(self, compartment_id: str, *, region: str) -> list[Any]:
        client = self._client(LimitsClient, region)
        return self._all(
            "limits.list_limit_definitions",
            region,
            client.list_limit_definitions,
            compartment_id,
        )

    def get_resource_availability(
        self,
        compartment_id: str,
        service_name: str,
        limit_name: str,
        *,
        region: str,
        availability_domain: str | None = None,
    ) -> Any:
        client = self._client(LimitsClient, region)
        kwargs = {"availability_domain": availability_domain} if availability_domain else {}
        return self._one(
            "limits.get_resource_availability",
            region,
            client.get_resource_availability,
            service_name,
            limit_name,
            compartment_id,
            **kwargs,
        )

    def list_topics(
        self, compartment_id: str, *, region: str, name: str | None = None
    ) -> list[Any]:
        client = self._client(NotificationControlPlaneClient, region)
        kwargs = {"name": name} if name else {}
        return self._all("ons.list_topics", region, client.list_topics, compartment_id, **kwargs)

    def create_topic(
        self, compartment_id: str, name: str, description: str, *, region: str
    ) -> Any:
        client = self._client(NotificationControlPlaneClient, region)
        details = CreateTopicDetails(
            compartment_id=compartment_id,
            name=name,
            description=description,
        )
        return self._one(
            "ons.create_topic",
            region,
            client.create_topic,
            details,
            opc_retry_token=str(uuid.uuid4()),
        )

    def list_subscriptions(
        self, compartment_id: str, topic_id: str, *, region: str
    ) -> list[Any]:
        client = self._client(NotificationDataPlaneClient, region)
        return self._all(
            "ons.list_subscriptions",
            region,
            client.list_subscriptions,
            compartment_id,
            topic_id=topic_id,
        )

    def create_subscription(
        self, compartment_id: str, topic_id: str, email: str, *, region: str
    ) -> Any:
        client = self._client(NotificationDataPlaneClient, region)
        details = CreateSubscriptionDetails(
            compartment_id=compartment_id,
            topic_id=topic_id,
            protocol="EMAIL",
            endpoint=email,
        )
        return self._one(
            "ons.create_subscription",
            region,
            client.create_subscription,
            details,
            opc_retry_token=str(uuid.uuid4()),
        )

    def publish_message(self, topic_id: str, title: str, body: str, *, region: str) -> Any:
        client = self._client(NotificationDataPlaneClient, region)
        details = MessageDetails(title=title, body=body)
        return self._one("ons.publish_message", region, client.publish_message, topic_id, details)

    def telemetry_snapshot(self) -> dict[str, int | float]:
        return self.telemetry.snapshot()

    def is_not_found_or_unsupported(self, exc: OciSdkError) -> bool:
        code = (exc.code or "").lower()
        message = str(exc).lower()
        return exc.status == 404 or code in {
            "notauthorizedornotfound",
            "notfound",
            "notavailable",
        } or any(value in message for value in ("not found", "notavailable", "not supported"))

    @staticmethod
    def to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        converted = oci.util.to_dict(value)
        return converted if isinstance(converted, dict) else {"value": converted}

    def _client(self, client_type: type[ClientT], region: str) -> ClientT:
        clients = getattr(self._local, "clients", None)
        if clients is None:
            clients = {}
            self._local.clients = clients
        key = (client_type, region)
        if key in clients:
            return clients[key]

        config, signer = self._authentication()
        config["region"] = region
        kwargs: dict[str, Any] = {
            "timeout": (
                self.settings.oci_connect_timeout_seconds,
                self.settings.oci_read_timeout_seconds,
            ),
            "retry_strategy": self._retry_strategy,
        }
        if signer is not None:
            kwargs["signer"] = signer
        client = client_type(config, **kwargs)
        clients[key] = client
        return client

    def _authentication(
        self,
    ) -> tuple[dict[str, Any], InstancePrincipalsSecurityTokenSigner | None]:
        with self._auth_lock:
            if self.settings.oci_auth_mode == "instance_principal":
                if self._signer is None:
                    self._signer = InstancePrincipalsSecurityTokenSigner()
                return {}, self._signer
            if self._profile_config is None:
                self._profile_config = oci.config.from_file(
                    file_location=str(Path(self.settings.oci_config_file).expanduser()),
                    profile_name=self.settings.oci_profile,
                )
            return dict(self._profile_config), None

    def _all(self, operation: str, region: str, method, *args, **kwargs) -> list[Any]:
        wait_started = time.monotonic()
        self._request_limiter.acquire()
        wait_seconds = time.monotonic() - wait_started
        self.telemetry.record_request(wait_seconds)
        try:
            with self.telemetry.operation(region, operation):
                return list(oci.pagination.list_call_get_all_results(method, *args, **kwargs).data)
        except (ServiceError, BaseRequestException, ClientError) as exc:
            self.telemetry.record_final_error(exc)
            raise self._error(operation, exc) from exc
        finally:
            self._request_limiter.release()

    def _one(self, operation: str, region: str, method, *args, **kwargs) -> Any:
        wait_started = time.monotonic()
        self._request_limiter.acquire()
        wait_seconds = time.monotonic() - wait_started
        self.telemetry.record_request(wait_seconds)
        try:
            with self.telemetry.operation(region, operation):
                return method(*args, **kwargs).data
        except (ServiceError, BaseRequestException, ClientError) as exc:
            self.telemetry.record_final_error(exc)
            raise self._error(operation, exc) from exc
        finally:
            self._request_limiter.release()

    @staticmethod
    def _error(
        operation: str,
        exc: ServiceError | BaseRequestException | ClientError,
    ) -> OciSdkError:
        if isinstance(exc, ServiceError):
            return OciSdkError(
                operation,
                exc.message or str(exc),
                status=exc.status,
                code=exc.code,
                opc_request_id=exc.request_id,
            )
        return OciSdkError(operation, str(exc))
