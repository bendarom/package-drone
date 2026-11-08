"""Telemetry readout (bench test, also the SITL link test). Read-only.

Connects, requests the message rates from config telemetry.rates_hz, then prints
mode, lidar, battery, GPS, throttle and measured message rates once a second.

  python tools/telemetry.py                                   # Pi, config.yaml
  python tools/telemetry.py --overlay sitl/config.sitl.yaml   # SITL
"""

import time

from _common import arg_parser, connect, load


def main():
    p = arg_parser(__doc__.splitlines()[0])
    p.add_argument("--duration", type=float, default=0, help="seconds to run (default: until Ctrl-C)")
    p.add_argument("--no-intervals", action="store_true",
                   help="don't send SET_MESSAGE_INTERVAL (just listen)")
    args = p.parse_args()
    cfg, log = load(args, "telemetry")
    link = connect(cfg, log)
    try:
        if not args.no_intervals:
            results = link.set_message_intervals()
            failed = [n for n, ok in results.items() if not ok]
            print(f"message intervals: {len(results) - len(failed)}/{len(results)} accepted"
                  + (f", not accepted: {', '.join(failed)}" if failed else ""))
        end = time.monotonic() + args.duration if args.duration else None
        while end is None or time.monotonic() < end:
            time.sleep(1)
            s = link.telemetry.snapshot(link.rate_types)
            rates = s.pop("rates_hz")
            print(" ".join(f"{k}={v}" for k, v in s.items()) + f" link_ok={link.link_ok}")
            print("  rates_hz: " + " ".join(
                f"{k}={v:g}/{cfg.telemetry.rates_hz[k]:g}" for k, v in rates.items()))
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
        log.close()


if __name__ == "__main__":
    main()
