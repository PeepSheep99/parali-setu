"""Who buys Punjab's paddy straw, and how much, from published figures.

No public dataset records company-level purchases over time, so this demand
side is *derived* from reported annual consumption by industry segment and
spread over the year (plants run year-round while straw is collected in about
six weeks). Every figure carries its source and the date it describes; the
ranges are kept where sources disagree. Nothing here is trained.
"""
from __future__ import annotations

from dataclasses import dataclass

LAKH = 100_000


@dataclass(frozen=True)
class Segment:
    key: str
    name: str
    annual_t_low: float
    annual_t_high: float
    as_of: str
    note: str
    sources: tuple[str, ...]


SEGMENTS: tuple[Segment, ...] = (
    Segment(
        "biomass_power", "Biomass power plants", 11.7 * LAKH, 11.7 * LAKH, "2024-25",
        "11 projects, 101.5 MW combined (PEDA); the state's NGT status report puts 2024 use at about 1.17 Mt.",
        ("https://bioenergytimes.com/four-cbg-plants-to-come-up-in-punjab-in-2026-27-to-consume-1-08-lakh-tonnes-of-paddy-residue/",),
    ),
    Segment(
        "cbg", "Compressed biogas (CBG) plants", 3.5 * LAKH, 5.4 * LAKH, "2024-25",
        "Six operating plants use about 3.5 lakh t (PEDA); the NGT status report gives 0.54 Mt for 2024. "
        "Verbio's Lehragaga plant alone is reported at about 1.3 lakh t a year.",
        ("https://bioenergytimes.com/four-cbg-plants-to-come-up-in-punjab-in-2026-27-to-consume-1-08-lakh-tonnes-of-paddy-residue/",
         "https://renewablewatch.in/2024/01/30/taking-action-cbg-helps-address-the-issue-of-stubble-burning-in-punjab/"),
    ),
    Segment(
        "industrial_boilers", "Industrial boilers", 36 * LAKH, 41 * LAKH, "2025 (projected)",
        "Boiler use grew from 8.8 lakh t in 2022 to a projected 41 lakh t in 2025; 36 new units add 11.28 lakh t.",
        ("https://bioenergytimes.com/punjab-targets-zero-stubble-burning-by-2030-with-biomass-cbg-and-crop-diversification-push/",
         "https://www.tribuneindia.com/news/punjab/to-counter-stubble-burning-punjab-govt-pushes-green-fuel-initiative"),
    ),
    Segment(
        "pellets", "Pellet plants (incl. thermal co-firing supply)", 7 * LAKH, 17 * LAKH, "2025",
        "37 plants operating and 34 more being set up, targeting 17 lakh t; about 7 lakh t expected this season. "
        "Pellets feed thermal plants under CAQM's co-firing directions.",
        ("https://bioenergytimes.com/punjab-targets-zero-stubble-burning-by-2030-with-biomass-cbg-and-crop-diversification-push/",),
    ),
)

# Ex-situ totals, for checking the segment sum against the state's own figures.
EX_SITU_TOTAL_T = {"2023": 3.66e6, "2024": 5.96e6, "2025 target": 7.0e6}
EX_SITU_SOURCE = (
    "https://www.greentribunal.gov.in/sites/default/files/news_updates/Status%20Report%20by%20State%20of%20Punjab"
    "%20in%20OA%20No.%20632%20of%202023%20(In%20Re%20News%20item%20published%20in%20The%20Hindu%20dated%2006.10.2023"
    "%20titled%20Pollution%20takes%20a%20front%20seat%20as%20Stubble%20Fires%20Spike%20in%20Punjab.pdf"
)


def segment_totals() -> tuple[float, float]:
    return sum(s.annual_t_low for s in SEGMENTS), sum(s.annual_t_high for s in SEGMENTS)
