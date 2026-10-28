"""graveyard-shift: ghost agents that work your night shift, on local Gemma 4, while you sleep.

  graveyard-shift                open the graveyard (leave a note, say goodnight, read the morning briefing)
  graveyard-shift night          work tonight: waits until you're asleep, then the ghosts rise
  graveyard-shift demo           a night on Marisol's (fictional) day, starting now
  graveyard-shift worker         just the worker: picks a night back up after a crash
  graveyard-shift awake          tell tonight's ghosts you're up
  graveyard-shift sleep-eval     how well TabPFN predicts your waking, against simpler guesses
  graveyard-shift --setup        download the models and make the app (the installer runs this)
"""
import argparse
import asyncio
import json
import sys

from . import night as nights


def main(argv=None):
    ap = argparse.ArgumentParser(prog="graveyard-shift", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="open",
                    choices=["open", "night", "demo", "worker", "awake", "sleep-eval", "forecast"])
    ap.add_argument("--note", help="what the ghosts should do tonight")
    ap.add_argument("--now", action="store_true", help="night: don't wait for sleep")
    ap.add_argument("--dawn-in", type=int, metavar="MIN", help="demo: dawn this many minutes from now")
    ap.add_argument("--wait", action="store_true", help="demo: wait for you to fall asleep, like a real night")
    ap.add_argument("--model", help="a specific local model (default: the biggest Gemma 4 that fits tonight)")
    ap.add_argument("--setup", action="store_true", help="download Gemma 4, TabPFN and Temporal; make the app")
    ap.add_argument("--skip-models", action="store_true", help="with --setup: only make the app")
    ap.add_argument("--every-night", action="store_true", help="with --setup: the ghosts rise every night (from 9 pm)")
    ap.add_argument("--uninstall", action="store_true", help="remove the app and the nightly run")
    args = ap.parse_args(argv)

    if args.setup or args.uninstall:
        from . import install
        return install.uninstall() if args.uninstall else install.setup(models=not args.skip_models, every_night=args.every_night)
    if args.command == "sleep-eval":
        from . import sleep
        return print(json.dumps(sleep.evaluate(), indent=1))
    if args.command == "forecast":
        from datetime import datetime
        from . import sleep
        f = sleep.forecast(datetime.now())
        return print(f"Likely back at the Mac around {f['wake'][11:16]}; briefing due by {f['dawn'][11:16]} "
                     f"({f['nights']} nights learned).")
    if args.command == "worker":
        return asyncio.run(nights.work_only())
    if args.command == "awake":
        return asyncio.run(_awake())
    if args.command in ("night", "demo"):
        night = asyncio.run(nights.running_night())
        if night:
            print(f"{night['id']} is still going: picking it up where it stopped.")
        else:
            night = (nights.persona_night(args.note, args.dawn_in, wait=args.wait) if args.command == "demo"
                     else nights.real_night(args.note or "", wait=not args.now))
            if args.model:
                night["model"] = args.model
            print(f"{night['id']}: the ghosts are {'waiting for you to fall asleep' if night['wait'] else 'rising'}.")
        print(f"Watch them: http://127.0.0.1:{nights.UI_PORT}/namespaces/default/workflows/{night['id']}")
        briefing = asyncio.run(nights.run(night, watch_touch=night["wait"]))
        done = briefing["night"]
        print(f"Dawn ({done['ended']}). Briefing: {night['dir']}/briefing.json")
        return
    from .server import serve
    serve()


async def _awake():
    from .workflow import NightShift
    client = await nights.connect()
    async for wf in client.list_workflows("WorkflowType='NightShift' AND ExecutionStatus='Running'"):
        await client.get_workflow_handle(wf.id).signal(NightShift.wake)
        print(f"Told {wf.id}: you're up.")


if __name__ == "__main__":
    sys.exit(main())
