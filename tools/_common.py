"""Shared setup for tools/ scripts. tools/ scripts are read-only: they never arm,
change modes or send movement commands (CLAUDE.md)."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DEFAULT_CONFIG, ConfigError, load_config  # noqa: E402
from mav.connection import LinkError, MavLink  # noqa: E402
from mav.log import open_run_log  # noqa: E402


def arg_parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="config file (default: config.yaml)")
    p.add_argument("--overlay", help="overlay merged on top, e.g. sitl/config.sitl.yaml")
    return p


def load(args, tool_name):
    """Config (connect level) and a run log. Exits with the config errors if invalid."""
    try:
        cfg = load_config(args.config, args.overlay)
    except ConfigError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    log = open_run_log(cfg)
    log.event("tool_start", tool_name, config=args.config, overlay=args.overlay, run_mode=cfg.run_mode)
    for w in cfg.warnings:
        log.warning("config_warning", w)
    return cfg, log


def connect(cfg, log):
    link = MavLink(cfg, log)
    try:
        return link.connect()
    except LinkError as e:
        log.error("connect_failed", str(e))
        link.close()
        log.close()
        sys.exit(3)
