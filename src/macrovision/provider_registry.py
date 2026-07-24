from collections.abc import Callable
from threading import RLock

from macrovision.config import Settings
from macrovision.fred_provider import FREDProvider
from macrovision.provider_contracts import (
    ExternalDataProvider,
    ProviderError,
    ProviderErrorCode,
)

ProviderFactory = Callable[[Settings], ExternalDataProvider]
MAX_PROVIDER_NAME_LENGTH = 40


def normalize_provider_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized or len(normalized) > MAX_PROVIDER_NAME_LENGTH:
        raise ProviderError(
            ProviderErrorCode.configuration_error,
            "Provider name is invalid",
            status_code=422,
        )
    if not normalized.replace("_", "").replace("-", "").isalnum():
        raise ProviderError(
            ProviderErrorCode.configuration_error,
            "Provider name is invalid",
            status_code=422,
        )
    return normalized


class ProviderRegistry:
    """Thread-safe, code-defined allowlist of external provider factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._lock = RLock()

    def register(self, name: str, factory: ProviderFactory) -> None:
        normalized = normalize_provider_name(name)
        with self._lock:
            if normalized in self._factories:
                raise ProviderError(
                    ProviderErrorCode.configuration_error,
                    "Provider is already registered",
                    status_code=409,
                )
            self._factories[normalized] = factory

    def create(self, name: str, settings: Settings) -> ExternalDataProvider:
        normalized = normalize_provider_name(name)
        with self._lock:
            factory = self._factories.get(normalized)
        if factory is None:
            raise ProviderError(
                ProviderErrorCode.configuration_error,
                "Provider is not supported",
                status_code=422,
            )
        return factory(settings)

    def supported_providers(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._factories))


_registry = ProviderRegistry()
_registry.register("fred", FREDProvider)


def get_provider_registry() -> ProviderRegistry:
    return _registry
