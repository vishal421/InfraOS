from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.entities import Device
from app.plugins.base import PluginError
from app.services import config_service, monitoring_service, twin_service
from sqlalchemy import select

logger = logging.getLogger("infraos.poller")

# Config drift checks are more expensive (full config pull + diff) than a
# metrics poll, so they run on a slower cadence — every Nth metrics cycle
# rather than every cycle. 10 cycles at the default 30s metrics interval is
# ~5 minutes, matching the "Continuous sync" cadence described in the
# architecture doc's Topology Discovery Engine section.
CONFIG_CHECK_EVERY_N_CYCLES = 10


class PollerService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._cycle_count = 0

    def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Poller started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
            logger.info("Poller stopped")

    async def _run_loop(self) -> None:
        settings = get_settings()
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Unhandled error in poller cycle — continuing on next cycle")

            self._cycle_count += 1
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=settings.metrics_poll_interval_seconds)
            except asyncio.TimeoutError:
                pass  # normal case: interval elapsed, loop again

    async def _poll_once(self) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(Device))
            devices = list(result.scalars().all())

        check_config_this_cycle = self._cycle_count % CONFIG_CHECK_EVERY_N_CYCLES == 0

        for device in devices:
            async with async_session_factory() as db:
                try:
                    await monitoring_service.collect_metrics(db, device.id)
                except PluginError as exc:
                    logger.warning("Metrics poll failed for device %s: %s", device.id, exc)
                    continue
                except Exception:
                    logger.exception("Unexpected error polling metrics for device %s", device.id)
                    continue

            if check_config_this_cycle:
                async with async_session_factory() as db:
                    try:
                        await config_service.collect_configuration(db, device.id)
                    except PluginError as exc:
                        logger.warning("Config drift check failed for device %s: %s", device.id, exc)
                    except Exception:
                        logger.exception("Unexpected error checking config drift for device %s", device.id)

            await twin_service.invalidate_twin_cache(device.id)


poller = PollerService()
