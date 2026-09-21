"""Orchestrator — penjadwalan schedule-driven memakai APScheduler.

Menjalankan agent pada jam yang tepat (WIB), plus loop monitor intraday.
Deterministik & hemat resource (tidak ada loop LLM mandiri).

Timeline harian (Senin–Jumat):
  07.45  Agent 1  Harvester (pra-pembukaan)
  20.00  Agent 1  Harvester (sesi malam)
  09.10  Agent 2  Analyst  → Agent 3  Quant  (berurutan)
  09.15  Agent 4  Reporter (email)
  16.10  Rekonsiliasi harian (nonaktifkan plan, reset watchlist runtime)
  jam bursa  Agent 5  polling harga tiap MONITOR_POLL_SECONDS
"""
from __future__ import annotations

import asyncio

from src.config import settings
from src.core import database as dbm
from src.core.logging_conf import get_logger

log = get_logger("orchestrator")


def _job_agent1() -> None:
    from src.agents import agent1_harvester
    agent1_harvester.run()


def _job_morning_analysis() -> None:
    """Agent 2 lalu Agent 3 secara berurutan (Agent 3 butuh output Agent 2)."""
    from src.agents import agent2_analyst, agent3_quant
    agent2_analyst.run()
    agent3_quant.run()


def _job_agent4() -> None:
    from src.agents import agent4_reporter
    agent4_reporter.run()


def _job_reconcile() -> None:
    log.info("Rekonsiliasi harian: nonaktifkan trade plan.")
    dbm.deactivate_plans()


async def _monitor_loop() -> None:
    from src.agents.agent5_monitor import poll_once
    while True:
        try:
            await poll_once()
        except Exception as exc:  # noqa: BLE001
            log.error("Monitor error: %s", exc)
        await asyncio.sleep(settings.monitor_poll_seconds)


def _parse_hm(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


async def serve() -> None:
    """Titik masuk async: pasang scheduler + loop monitor."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    dbm.init_db()
    tz = settings.timezone
    sched = AsyncIOScheduler(timezone=tz)

    # Agent 1 — pra-pembukaan & malam.
    sched.add_job(_job_agent1, CronTrigger(day_of_week="mon-fri", hour=7, minute=45, timezone=tz),
                  id="agent1_am", replace_existing=True)
    sched.add_job(_job_agent1, CronTrigger(day_of_week="mon-fri", hour=20, minute=0, timezone=tz),
                  id="agent1_pm", replace_existing=True)

    # Agent 2 + 3 — 09.10 WIB.
    sched.add_job(_job_morning_analysis,
                  CronTrigger(day_of_week="mon-fri", hour=9, minute=10, timezone=tz),
                  id="morning_analysis", replace_existing=True)

    # Agent 4 — 09.15 WIB (email).
    sched.add_job(_job_agent4, CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=tz),
                  id="agent4_email", replace_existing=True)

    # Rekonsiliasi — 16.10 WIB.
    sched.add_job(_job_reconcile, CronTrigger(day_of_week="mon-fri", hour=16, minute=10, timezone=tz),
                  id="reconcile", replace_existing=True)

    sched.start()
    log.info("Scheduler aktif (TZ=%s). Job: %s", tz, [j.id for j in sched.get_jobs()])

    # Agent 5 — loop monitor intraday (cek jam bursa di dalam poll_once).
    await _monitor_loop()


def main() -> None:
    try:
        asyncio.run(serve())
    except (KeyboardInterrupt, SystemExit):
        log.info("Orchestrator dihentikan.")


if __name__ == "__main__":
    main()
