"""Download the corpus documents listed in docs/catalog.yaml.

Entries with `download: auto` are fetched; `download: manual` ones are listed with
their URLs to save from a browser. Existing files are skipped unless --force.
Run: python scripts/download_docs.py [--force] [--only FILE ...]
"""

import argparse
import sys
import urllib.request

from pharmassist.catalog import docs_dir, load_catalog

# some government sites reject Python's default "Python-urllib" agent even though curl works
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 60


def download(url: str, dest) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # urlopen raises HTTPError on 4xx/5xx, so an error page is never saved (like curl -f)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, tmp.open("wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    parser.add_argument("--only", nargs="+", metavar="FILE", help="limit to these catalog files or ids")
    args = parser.parse_args()

    docs = docs_dir()
    docs.mkdir(exist_ok=True)
    entries = load_catalog()
    if args.only:
        entries = [e for e in entries if e["file"] in args.only or e["id"] in args.only]
        if not entries:
            print(f"no catalog entries match {args.only}", file=sys.stderr)
            return 1
    failed, manual = [], []

    for e in entries:
        dest = docs / e["file"]
        if e["download"] == "manual":
            if not dest.exists():
                manual.append(e)
            continue
        if dest.exists() and not args.force:
            print(f"skip  {e['file']} (exists)")
            continue
        print(f"get   {e['file']} …", flush=True)
        try:
            download(e["source_url"], dest)
            print(f"      ok ({dest.stat().st_size / 1024:.0f} KB)")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            print(f"      FAILED: {exc}  {e['source_url']}", file=sys.stderr)
            failed.append(e["file"])

    if manual:
        print("\nManual downloads needed (open in a browser, save into docs/ with these names):")
        for e in manual:
            print(f"  - {e['file']}\n      {e['source_url']}")
    print("\nThen run: python scripts/parse_docs.py")

    if failed:
        print(f"\n{len(failed)} download(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
