from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.redis_client import get_redis
from app.schemas.schemas import (
    ConfigVersionSummary,
    DeviceResponse,
    DigitalTwinResponse,
    HealthEventResponse,
    MetricPoint,
)
from app.services import config_service, monitoring_service
from app.services.device_service import get_device

CACHE_KEY_PREFIX = "twin:"


async def get_digital_twin(db: AsyncSession, device_id: str, use_cache: bool = True) -> DigitalTwinResponse:
    settings = get_settings()
    redis = get_redis()
    cache_key = f"{CACHE_KEY_PREFIX}{device_id}"

    if use_cache:
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["cache_hit"] = True
            return DigitalTwinResponse.model_validate(data)

    device = await get_device(db, device_id)
    latest_config = await config_service.get_latest_config_version(db, device_id)
    latest_metrics = await monitoring_service.get_latest_metrics(db, device_id)
    active_events = await monitoring_service.list_health_events(db, device_id, active_only=True)

    twin = DigitalTwinResponse(
        device=DeviceResponse.model_validate(device),
        latest_config=ConfigVersionSummary.model_validate(latest_config) if latest_config else None,
        latest_metrics={
            name: MetricPoint.model_validate(record) for name, record in latest_metrics.items()
        },
        active_health_events=[HealthEventResponse.model_validate(e) for e in active_events],
        generated_at=datetime.now(timezone.utc),
        cache_hit=False,
    )

    await redis.set(
        cache_key,
        twin.model_dump_json(),
        ex=settings.digital_twin_cache_ttl_seconds,
    )
    return twin


async def invalidate_twin_cache(device_id: str) -> None:
    redis = get_redis()
    await redis.delete(f"{CACHE_KEY_PREFIX}{device_id}")
