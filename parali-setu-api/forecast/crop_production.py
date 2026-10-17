"""How much paddy straw each district produces, from government crop statistics.

Source: the Ministry of Agriculture's Area-Production-Yield (APY) statistics,
1997-2019, as mirrored on Kaggle ("India Agriculture Crop Production",
pyatakov/india-agriculture-crop-production). Only Punjab and Haryana rice
rows are used.

Straw is estimated from grain with a residue-to-grain ratio of 1.5, the
figure commonly used for paddy in Indian biomass assessments. As a check,
Punjab's 2019 crop of 12.68 Mt x 1.5 = 19.0 Mt, against the state's own
estimate of about 19.7 Mt of paddy straw.

    python -m forecast.crop_production --raw "forecast/data/raw/pyatakov/India Agriculture Crop Production.csv"
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

STRAW_TO_GRAIN = 1.5
STATES = ("Punjab", "Haryana")
FIELDS = ("year", "state", "district", "rice_area_ha", "rice_t", "straw_t")

# Spellings in the APY data that differ from the FAO GAUL 2025 boundaries
# used for the fire series. Keys are upper-case APY names.
ALIASES = {
    "FIROZEPUR": "Firozpur", "FEROZEPUR": "Firozpur", "MUKTSAR": "Sri Muktsar Sahib",
    "NAWANSHAHR": "Shahid Bhagat Singh Nagar", "SHAHEED BHAGAT SINGH NAGAR": "Shahid Bhagat Singh Nagar",
    "S.A.S NAGAR": "Sahibzada Ajit Singh Nagar", "S.A.S. NAGAR": "Sahibzada Ajit Singh Nagar",
    "SAS NAGAR": "Sahibzada Ajit Singh Nagar", "MOHALI": "Sahibzada Ajit Singh Nagar",
    "RUPNAGAR": "Rupnagar", "ROPAR": "Rupnagar", "GURGAON": "Gurugram", "MEWAT": "Nuh",
    "TARN TARAN": "Tarn Taran", "FATEHGARH SAHIB": "Fatehgarh Sahib", "YAMUNANAGAR": "Yamuna Nagar",
    "SONIPAT": "Sonipat", "SONEPAT": "Sonipat", "CHARKI DADRI": "Charkhi Dadri",
}


def normalise_district(name: str) -> str:
    key = " ".join(name.strip().upper().split())
    return ALIASES.get(key, key.title())


def year_of(value: str) -> int:
    """'2019-20' and '2019' both mean the 2019 kharif (paddy) season."""
    return int(value.strip()[:4])


def rice_rows(raw_csv: Path) -> list[dict]:
    totals: dict[tuple[int, str, str], list[float]] = {}
    with raw_csv.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            state = r["State"].strip()
            if state not in STATES or r["Crop"].strip() != "Rice":
                continue
            if r.get("Production Units", "Tonnes").strip() != "Tonnes" or not r["Production"].strip():
                continue
            key = (year_of(r["Year"]), state, normalise_district(r["District"]))
            area, prod = totals.setdefault(key, [0.0, 0.0])
            totals[key] = [area + float(r["Area"] or 0), prod + float(r["Production"])]
    return [
        {"year": y, "state": s, "district": d, "rice_area_ha": round(a, 1), "rice_t": round(p, 1),
         "straw_t": round(p * STRAW_TO_GRAIN, 1)}
        for (y, s, d), (a, p) in sorted(totals.items())
    ]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("forecast/data/rice_production.csv"))
    args = parser.parse_args(argv)
    rows = rice_rows(args.raw)
    write_csv(rows, args.out)
    latest = max(r["year"] for r in rows)
    punjab = sum(r["rice_t"] for r in rows if r["year"] == latest and r["state"] == "Punjab")
    print(f"wrote {len(rows)} rows to {args.out}; Punjab {latest}: {punjab / 1e6:.2f} Mt rice, "
          f"{punjab * STRAW_TO_GRAIN / 1e6:.2f} Mt straw")


if __name__ == "__main__":
    main()
