"""Ask the agent one or more questions and print each answer, citations with links, time and cost.

Run: python scripts/ask.py "question" ["another question" ...] [--save-trace]
Uses the v2 router (OpenAI first, Sonnet fallback) and the PostgreSQL store (DATABASE_URL, as the API
and the worker do). Source PDFs are read from docs/ (the catalog's `file`), as the API does from its S3 cache.
"""

import argparse
import sys

from pharmassist.agent import ask, telemetry
from pharmassist.agent.tools import ToolBox
from pharmassist.config import PROJECT_ROOT, load_config
from pharmassist.llm.router import router_from_config


def show(r: dict):
    fallback = " (fallback used)" if r["fallback_used"] else ""
    print(f"\nQ: {r['question']}")
    print(f"Status: {r['status']} (agent: {r['agent_status']})   Answered by: {r['provider']}/{r['model']}{fallback}")
    print(f"\n{r['answer']}\n")
    if r["citations"]:
        print("Citations:")
        for c in r["citations"]:
            mark = f"  [UNVERIFIED: {c['flag']}]" if c["flag"] else ""
            where = f"row {c['row']}" if c.get("row") is not None else f"p{c['page']}"
            print(f"  - {c['doc_id']} {where}  {c['link']}{mark}")
    for line in r["conflicts_noted"]:
        print(f"Conflict noted: {line}")
    if r["flags"]:
        print(f"Flags: {', '.join(r['flags'])}")
    if r["needs_review"]:
        print("Needs pharmacist review before acting.")

    t, tok = r["timing_s"], r["tokens"]
    calls = t["model_calls"]
    print(f"\nTime {t['total']:.1f}s  (model {sum(calls):.1f}s over {len(calls)} calls "
          f"[{', '.join(f'{c:.1f}' for c in calls)}], search {t['search']:.1f}s, read_page {t['read_page']:.2f}s, "
          f"lookups {t['lookups']:.2f}s)")
    print(f"Lookups {r['lookups']}  |  tokens in {tok['input']:,} + cache read {tok['cache_read']:,} "
          f"+ cache write {tok['cache_write']:,}, out {tok['output']:,}  |  cost ${r['cost_usd']:.4f}")
    if r.get("trace_path"):
        print(f"Trace: {r['trace_path']}")
    if r.get("trace_id"):
        print(f"LangSmith run: {r['trace_id']}")


def open_store(cfg: dict):
    """The PostgreSQL store from database.url_env (DATABASE_URL). A clear message, not a traceback, when unset."""
    import os
    from pharmassist.store import open_store as _open
    env_name = (cfg.get("database") or {}).get("url_env", "DATABASE_URL")
    dsn = os.environ.get(env_name)
    if not dsn:
        sys.exit(f"set {env_name} (see deploy/docker-compose.yml for the local stack)")
    return _open(dsn)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="+")
    parser.add_argument("--save-trace", action="store_true", help="write the full JSON trace under traces/")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    cfg = load_config()
    router = router_from_config(cfg)
    store = open_store(cfg)
    for i, q in enumerate(args.questions):
        if i:
            print("\n" + "-" * 72)
        tools = ToolBox(store, embed=lambda text: router.embed([text])[0], cfg=cfg, question=q)  # PDFs from docs/ (the default resolver)
        show(ask(q, router=router, tools=tools, cfg=cfg, save_trace=args.save_trace))
    telemetry.flush()  # bounded wait for queued LangSmith traces (a no-op when tracing is off)


if __name__ == "__main__":
    main()
