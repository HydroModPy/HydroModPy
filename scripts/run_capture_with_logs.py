#!/usr/bin/env python3
from __future__ import annotations
import argparse, logging, sys
from hydromodpy.validity_frame.auto_capture import RuntimeAutoCapture, ExecutionContext

class ListHandler(logging.Handler):
    def __init__(self, lst):
        super().__init__()
        self.lst = lst
    def emit(self, record):
        self.lst.append(self.format(record))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-toml", type=str)
    parser.add_argument("--callable", type=str)
    parser.add_argument("--run-id", type=str, default="run_with_logs")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    logs = []
    lh = ListHandler(logs)
    lh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(lh)
    logging.getLogger().setLevel(logging.INFO)

    ctx = ExecutionContext(run_id=args.run_id, workspace=".")
    cap = RuntimeAutoCapture(context=ctx, output_dir=args.output_dir)

    def work():
        logging.info("start job")
        if args.callable:
            module, _, attr = args.callable.partition(":")
            mod = __import__(module, fromlist=[attr or ""])
            fn = getattr(mod, attr or "main")
            return fn()
        if args.project_toml:
            from hydromodpy import Project
            p = Project(args.project_toml)
            return p.run()
        logging.info("no action specified")
        return None

    res, snap = cap.run_with_capture(work, logs=logs)
    print("Result:", res)
    print("Snapshot dir:", cap.output_dir)

if __name__ == "__main__":
    main()
