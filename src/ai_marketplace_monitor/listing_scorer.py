"""Advanced rule-based listing scorer for car flipping.

Replaces AI evaluation with a fast, deterministic regex+keyword scorer.
Designed to filter out time-wasters and surface profitable listings ASAP.

Rejection levels (configurable per item via `rejection_level`):
  - "firehose":   see everything that isn't a hard-reject       (threshold = -99)
  - "lenient":    skip obvious junk                              (threshold = -3)
  - "normal":     balanced — skip junk & most red flags          (threshold =  0)
  - "strict":     only listings with at least 1 positive signal  (threshold =  3)
  - "best_only":  only the cream of the crop                     (threshold =  6)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# === HARD REJECT PATTERNS ===
# Any match here = instant reject, no scoring needed.
# Order matters minimally — these are OR'd into one regex.
HARD_REJECT_PATTERNS: Tuple[str, ...] = (
    r"\bcash\s*for\s*cars?\b",
    r"\bcar\s*removal\b",
    r"\bfree\s*removal\b",
    r"\bwe\s*buy\b",
    r"\bbuying\s*cars?\b",
    r"\bwrecking\b",
    r"\bwreckers?\b",
    r"\bscrap(?:ping)?\b",
    r"\bdismantling\b",
    r"\bparts\s*only\b",
    r"\bcar\s*parts\b",
    r"\bspares\s*or\s*repairs?\b",
    r"\bswap(?:s|ping)?\b",
    r"\bswap\s*(?:or|and|/)?\s*(?:trade|sell|deal)\b",
    r"\bsell\s*(?:or|and|/)?\s*(?:swap|trade)\b",
    r"\bopen\s*to\s*(?:swaps?|trades?)\b",
    r"\btrade(?:s|d|in)?\s*(?:for|only|considered|welcome|in)\b",
    r"\bfor\s*parts\b",
    r"\bparts\s*cars?\b",
    r"\bpart[-\s]?out\b",
    r"\bblown\s*head\s*gasket\b",
    r"\bhgs?\s*(?:gone|blown|leaking|leak)\b",        # "HG gone"
    # --- Tyres / mags / wheels / rims sold as accessories (not whole cars) ---
    r"\b(?:tyres?|tires?|mags?|wheels?|rims?|alloys?)\s+(?:and|&|\+)\s*(?:tyres?|tires?|mags?|wheels?|rims?|alloys?)\b",
    r"\bset\s*of\s*(?:4\s*)?(?:tyres?|tires?|mags?|wheels?|rims?|alloys?)\b",
    r"\b\d+\s*x?\s*(?:tyres?|tires?|mags?|rims?|alloys?)\b",   # "4 tyres", "4x mags"
    r"\b(?:tyres?|tires?|mags?|wheels?|rims?|alloys?)\s+for\s+sale\b",
    r"\bbrand\s*new\s*(?:tyres?|tires?|mags?|wheels?|rims?|alloys?)\b",
    r"\b(?:tyres?|tires?|mags?|alloys?)\s+\d+x\d+\b",          # "tyres 215x60"
    r"\b\d+\s*(?:inch|\"\s*)\s*(?:mags?|wheels?|rims?|alloys?)\b",   # "17 inch mags"
    # --- Body kit / aero parts (not whole cars) ---
    r"\blip\s*kits?\b",
    r"\bbody\s*kits?\b",
    r"\bspoilers?\b",
    r"\b(?:fender|wheel|guard)\s*flares?\b",
    r"\b\d+pcs?\s*flares?\b",                              # "4pc flares"
    r"\bside\s*skirts?\b",
    r"\bbumper\s+(?:lip|cover|kit|guard|spoiler)\b",
    r"\bdiffuser\s*(?:kit|set)?\b",
    r"\bcanards?\b",
    r"\bwidebody\s*kits?\b",
    # --- Turbocharger components / standalone turbo parts ---
    r"\bturbocharger\b",                                   # the noun specifically
    r"\bcompressor\s*wheel\b",
    r"\bturbine\s*wheel\b",
    r"\bbillet\s*(?:compressor|wheel|turbo)\b",
    r"\bv[-\s]?band\s*(?:entry|exit|flange|clamp)\b",
    r"\bT\s*\d\s*/\s*T\s*\d\b",                            # T3/T4 flange
    r"\bexhaust\s*manifold\b",
    r"\bintercoolers?\b",
    r"\bdownpipes?\b",
    r"\bwastegates?\b",
    r"\b(?:blow[-\s]?off\s*valve|BOV)\b",
    r"\bturbo\s*manifold\b",
    r"\bexternal\s*wastegate\b",
    # Turbo model numbers: G25-550, G30-660, GT3582, GTX3076, S366, EFR7163, K04, etc.
    r"\bG\d{2,3}[-\s]?\d{3,4}\b",
    r"\bGT[XR]?\d{3,5}\b",
    r"\bS\d{3,4}(?:SXE|SXR|SX)?\b",
    r"\bEFR\s*\d{4}\b",
    r"\bK\d{2,3}\s*turbo\b",
    r"\bHX\d{2,3}\b",                                       # Holset HX35 etc.
    r"\bwanted\b",
    r"\bwtb\b",                   # want to buy
    r"\btowing\b",
    r"\bblown\s*(?:engine|motor|head\s*gasket)\b",
    r"\bhead\s*gasket\s*(?:gone|blown|leak)",
    r"\bno\s*engine\b",
    r"\bnon[-\s]*runner\b",
    r"\bnot\s*running\b",
    r"\b(?:won'?t|doesn'?t|wont|doesnt)\s*start\b",
    r"\bneeds?\s*(?:engine|gearbox|transmission|new\s*motor)\b",
    r"\bwritten\s*off\b",
    r"\bwrite[-\s]*off\b",
    r"\bsalvage\b",
    r"\bdamaged\s*repairable\b",
    r"\bauto\s*recycling\b",
    r"\bproject\s*car\b",
    r"\bdrift\s*car\b",
    r"\brace\s*car\b",
)

_HARD_REJECT_RE = re.compile("|".join(HARD_REJECT_PATTERNS), re.IGNORECASE)


# === NEGATIVE SIGNALS ===
# (regex pattern, weight, label)
NEGATIVE_SIGNALS: Tuple[Tuple[str, int, str], ...] = (
    (r"\bno\s*wof\b",                   -3, "no WOF"),
    (r"\bno\s*rego\b",                  -3, "no rego"),
    (r"\b(?:wof|rego)\s*expired\b",     -2, "WOF/rego expired"),
    (r"\bexpired\s*(?:wof|rego)\b",     -2, "expired WOF/rego"),
    (r"\bderegistered\b",               -3, "deregistered"),
    (r"\bas[-\s]?is\b",                 -2, "sold as-is"),
    (r"\bneeds?\s*work\b",              -2, "needs work"),
    (r"\bneeds?\s*tlc\b",               -2, "needs TLC"),
    (r"\bmechanical\s*issues?\b",       -3, "mechanical issues"),
    (r"\bengine\s*(?:light|warning)\b", -2, "engine light"),
    (r"\bcheck\s*engine\b",             -2, "check engine"),
    (r"\brusty\b",                      -2, "rust"),
    (r"\brust\b",                       -1, "rust mention"),
    (r"\bleaks?\b",                     -2, "leaks"),
    (r"\bsmokes?\b",                    -3, "smokes"),
    (r"\bburn(?:s|ing)?\s*oil\b",       -3, "burns oil"),
    (r"\bhigh\s*km?s?\b",               -1, "high km"),
    (r"\bhigh\s*mileage\b",             -1, "high mileage"),
    (r"\bfirst\s*to\s*see\b",           -1, "pushy seller"),
    (r"\bquick\s*sale\b",               -1, "quick sale (suspect)"),
    (r"\burgent\b",                     -1, "urgent (suspect)"),
    (r"\bmoving\s*(?:overseas|country|abroad)\b", -2, "moving overseas (scam pattern)"),
    (r"\bno\s*offers?\b",               -1, "no offers (inflated)"),
    (r"\bfirm\s*price\b",               -1, "firm price"),
    (r"\bauction\b",                    -1, "auction"),
    (r"\bcrashed?\b",                   -3, "crashed"),
    (r"\baccident\b",                   -2, "accident"),
    (r"\brolled\b",                     -3, "rolled"),
    (r"\bflood(?:ed|\s*damage)?\b",     -3, "flood damaged"),
    (r"\bmodified\b",                   -1, "modified"),
    (r"\blowered\b",                    -1, "lowered"),
    (r"\bturbo'?d\b",                   -1, "turbo'd"),
    (r"\bdealer\b",                     -1, "dealer (often marked up)"),
)

# === POSITIVE SIGNALS ===
POSITIVE_SIGNALS: Tuple[Tuple[str, int, str], ...] = (
    (r"\bnew\s*wof\b",                   +3, "new WOF"),
    (r"\bfresh\s*wof\b",                 +3, "fresh WOF"),
    (r"\blong\s*wof\b",                  +2, "long WOF"),
    (r"\bnew\s*rego\b",                  +2, "new rego"),
    (r"\blong\s*rego\b",                 +2, "long rego"),
    (r"\b(?:11|12)\s*months?\s*(?:wof|rego)\b", +2, "12 months WOF/rego"),
    (r"\bnew\s*ty[re|ire]res?\b",        +1, "new tyres"),
    (r"\bnew\s*battery\b",               +1, "new battery"),
    (r"\b(?:just|recently)\s*serviced\b", +1, "just serviced"),
    (r"\bfull\s*service\s*history\b",    +2, "full service history"),
    (r"\bservice\s*history\b",           +1, "service history"),
    (r"\b(?:one|1|single)\s*owner\b",    +2, "one owner"),
    (r"\bnon[-\s]*smoker\b",             +1, "non-smoker"),
    (r"\bgaraged\b",                     +1, "garaged"),
    (r"\blow\s*km?s?\b",                 +2, "low km"),
    (r"\blow\s*mileage\b",               +2, "low mileage"),
    (r"\btidy\b",                        +1, "tidy"),
    (r"\bimmaculate\b",                  +2, "immaculate"),
    (r"\bexcellent\s*condition\b",       +1, "excellent condition"),
    (r"\bgreat\s*condition\b",           +1, "great condition"),
    (r"\bmint\s*condition\b",            +2, "mint condition"),
    (r"\bnz[-\s]*new\b",                 +1, "NZ new"),
    (r"\bbooks?\s*(?:and|&)\s*keys?\b",  +1, "books and keys"),
    (r"\b2\s*keys?\b",                   +1, "2 keys"),
    (r"\bregularly\s*serviced\b",        +1, "regularly serviced"),
    (r"\bcambelt\s*(?:done|replaced)\b", +2, "cambelt done"),
    (r"\btiming\s*belt\s*(?:done|replaced)\b", +2, "timing belt done"),
)


# Compile once
_NEGATIVE_RES = [(re.compile(p, re.IGNORECASE), w, l) for p, w, l in NEGATIVE_SIGNALS]
_POSITIVE_RES = [(re.compile(p, re.IGNORECASE), w, l) for p, w, l in POSITIVE_SIGNALS]


# === KM / YEAR HEURISTICS ===
_KM_RE = re.compile(
    r"\b(\d{2,3}(?:[,.]?\d{3})?|\d+)\s*(?:k|kms?|kilom)\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")


def _extract_km(text: str) -> int | None:
    """Try to extract kilometres from text. Returns km as int or None."""
    for match in _KM_RE.finditer(text):
        raw = match.group(1).replace(",", "").replace(".", "")
        unit_hint = match.group(0).lower()
        try:
            n = int(raw)
        except ValueError:
            continue
        # "150k" -> 150000; "150000kms" -> 150000
        if n < 1000 and ("k" in unit_hint and "km" not in unit_hint and "kilom" not in unit_hint):
            n *= 1000
        if 1000 <= n <= 1_000_000:
            return n
    return None


def _extract_year(text: str) -> int | None:
    """Extract first plausible vehicle year."""
    match = _YEAR_RE.search(text)
    if match:
        return int(match.group(1))
    return None


# === REJECTION LEVELS ===
THRESHOLDS = {
    "firehose":  -99,
    "lenient":   -3,
    "normal":    0,
    "strict":    3,
    "best_only": 6,
}


@dataclass
class ScoreResult:
    score: int = 0
    rejected: bool = False
    hard_reject: bool = False
    reasons: List[str] = field(default_factory=list)
    km: int | None = None
    year: int | None = None

    @property
    def summary(self) -> str:
        if self.hard_reject:
            return f"❌ HARD REJECT: {', '.join(self.reasons)}"
        sign = "✅" if self.score >= 3 else ("⚠️" if self.score >= 0 else "❌")
        bits = [f"{sign} Score: {self.score}"]
        if self.km is not None:
            bits.append(f"{self.km // 1000}k km")
        if self.year is not None:
            bits.append(f"{self.year}")
        if self.reasons:
            bits.append(" | ".join(self.reasons))
        return " · ".join(bits)


# Placeholder/junk prices that almost always indicate the seller didn't bother
# entering a real price. $1,234 is the famous one (keyboard walk).
PLACEHOLDER_PRICES = {1234.0, 12345.0, 1111.0, 9999.0, 11111.0, 99999.0}


def is_placeholder_price(price_value: Optional[float]) -> bool:
    return price_value is not None and price_value in PLACEHOLDER_PRICES


def score_listing(
    title: str,
    description: str = "",
    rejection_level: str = "normal",
    price_value: Optional[float] = None,
) -> ScoreResult:
    """Score a listing. Higher = better. Hard rejects bypass scoring."""
    text = f"{title or ''} {description or ''}"
    result = ScoreResult()

    # 0) Placeholder price = junk listing
    if is_placeholder_price(price_value):
        result.hard_reject = True
        result.rejected = True
        result.score = -99
        result.reasons.append(f"hard:placeholder_price_${int(price_value)}")
        return result

    # 1) HARD REJECT — instant skip
    hard = _HARD_REJECT_RE.search(text)
    if hard:
        result.hard_reject = True
        result.rejected = True
        result.score = -99
        result.reasons.append(f"hard:{hard.group(0).lower()}")
        return result

    # 2) Negative signals
    for regex, weight, label in _NEGATIVE_RES:
        if regex.search(text):
            result.score += weight
            result.reasons.append(f"{weight:+d} {label}")

    # 3) Positive signals
    for regex, weight, label in _POSITIVE_RES:
        if regex.search(text):
            result.score += weight
            result.reasons.append(f"{weight:+d} {label}")

    # 4) KM-based penalties (only if extracted)
    km = _extract_km(text)
    if km is not None:
        result.km = km
        if km > 300_000:
            result.score -= 4
            result.reasons.append("-4 very high km (>300k)")
        elif km > 250_000:
            result.score -= 2
            result.reasons.append("-2 high km (>250k)")
        elif km < 100_000:
            result.score += 2
            result.reasons.append("+2 low km (<100k)")
        elif km < 150_000:
            result.score += 1
            result.reasons.append("+1 moderate km (<150k)")

    # 5) Year-based penalties
    year = _extract_year(text)
    if year is not None:
        result.year = year
        if year < 2000:
            result.score -= 3
            result.reasons.append("-3 very old (<2000)")
        elif year < 2005:
            result.score -= 1
            result.reasons.append("-1 old (<2005)")
        elif year >= 2015:
            result.score += 1
            result.reasons.append("+1 newer (2015+)")

    # 6) Apply threshold
    threshold = THRESHOLDS.get(rejection_level, THRESHOLDS["normal"])
    result.rejected = result.score < threshold
    return result
