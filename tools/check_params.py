"""Standalone parameter check (bench test, also the SITL test). Read-only.

Reads every parameter in params/expected_<real|sitl>.yaml from the FC and prints
PASS / FAIL / MISSING / TBD for each. Exit code 0 only if all pass.

  python tools/check_params.py                                   # Pi
  python tools/check_params.py --overlay sitl/config.sitl.yaml   # SITL
"""

import sys

from _common import arg_parser, connect, load

from mav.params import ParamFileError, check_params, load_expected


def main():
    p = arg_parser(__doc__.splitlines()[0])
    p.add_argument("--expected", choices=("real", "sitl"),
                   help="which expected file to use (default: from run_mode; shadow uses real)")
    args = p.parse_args()
    cfg, log = load(args, "check_params")
    try:
        path, entries = load_expected(args.expected or cfg.run_mode)
    except ParamFileError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    link = connect(cfg, log)
    try:
        log.event("param_check_start", f"{len(entries)} parameters from {path.name}")
        report = check_params(link.read_param, entries, log, path.name)
    finally:
        link.close()
        log.close()
    print()
    for r in report.results:
        print(r.describe())
    print(report.summary())
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
