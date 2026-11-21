"""Extract the NYRx PDL drug rows into index/tables/ (the VA formulary is read directly; it loads in
under a second).

Run: python scripts/build_tables.py
"""

import argparse

from pharmassist.tables import ny_pdl, va_formulary


def main():
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    manifest = ny_pdl.build()
    print(f"NY PDL: {manifest['rows']} rows from pages {manifest['pages'][0]}–{manifest['pages'][1]} "
          f"-> {ny_pdl.artifact_path()}")
    f = va_formulary.load()
    print(f"VA formulary: {len(f.rows)} rows, header row {f.header_row}, rule row {f.rule_row}, "
          f"PA row {f.pa_row}")


if __name__ == "__main__":
    main()
