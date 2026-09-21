"""Entrypoint CLI.

Contoh:
  python -m src.cli serve                 # orchestrator penuh (scheduler + monitor)
  python -m src.cli bot                    # jalankan bot Telegram
  python -m src.cli run-agent 1            # jalankan satu agent sekali
  python -m src.cli run-agent 2 --dry-run
  python -m src.cli pipeline               # jalankan Agent 1→2→3→4 berurutan
  python -m src.cli init-db                # buat skema DB
"""
from __future__ import annotations

import argparse

from src.config import settings
from src.core import database as dbm
from src.core.logging_conf import get_logger

log = get_logger("cli")


def _run_agent(num: int) -> None:
    if num == 1:
        from src.agents import agent1_harvester as m; m.run()
    elif num == 2:
        from src.agents import agent2_analyst as m; m.run()
    elif num == 3:
        from src.agents import agent3_quant as m; m.run()
    elif num == 4:
        from src.agents import agent4_reporter as m; m.run()
    elif num == 5:
        import asyncio
        from src.agents.agent5_monitor import run_forever
        asyncio.run(run_forever())
    elif num == 6:
        log.info("Agent 6 bersifat on-demand via bot Telegram (kirim screenshot). "
                 "Jalankan: python -m src.cli bot")
    else:
        raise SystemExit(f"Agent tidak dikenal: {num}")


def _pipeline() -> None:
    """Jalankan alur pagi lengkap sekali (untuk uji end-to-end)."""
    from src.agents import (
        agent1_harvester, agent2_analyst, agent3_quant, agent4_reporter,
    )
    agent1_harvester.run()
    agent2_analyst.run()
    agent3_quant.run()
    agent4_reporter.run()


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading-agent-tio")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="Jalankan orchestrator (scheduler + monitor)")
    sub.add_parser("bot", help="Jalankan bot Telegram (Agent 5/6)")
    sub.add_parser("pipeline", help="Jalankan Agent 1→4 berurutan sekali")
    sub.add_parser("init-db", help="Inisialisasi skema database")

    ra = sub.add_parser("run-agent", help="Jalankan satu agent")
    ra.add_argument("number", type=int, choices=range(1, 7))
    ra.add_argument("--dry-run", action="store_true", help="Jangan kirim notifikasi sungguhan")

    args = parser.parse_args()

    if getattr(args, "dry_run", False):
        settings.dry_run = True
        log.info("Mode DRY_RUN aktif.")

    if args.cmd == "serve":
        from src.orchestrator import main as serve_main
        serve_main()
    elif args.cmd == "bot":
        from src.telegram_bot import run_bot
        run_bot()
    elif args.cmd == "pipeline":
        _pipeline()
    elif args.cmd == "init-db":
        dbm.init_db()
        log.info("Skema DB dibuat di %s", settings.db_path)
    elif args.cmd == "run-agent":
        _run_agent(args.number)


if __name__ == "__main__":
    main()
