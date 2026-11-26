"""Expert mapping: linguistic indicator -> broader racism subcategory.

TRACE annotates each text with racism categories (Διάκριση, Αφομοίωση) and, under
each one, the linguistic means (indicators) that realise it. The project groups
those 11 indicators into 5 broader subcategories:

Διάκριση (discrimination)
    Ο/Η Άλλος/η ως πρόβλημα          the Other as a problem
    Ο/Η απομακρυσμένος/η Άλλος/η      the distant Other
    Ο/Η παθητικός/η Άλλος/η           the passive Other
Αφομοίωση (assimilation)
    Ασθενής αφομοίωση                 weak assimilation
    Ισχυρή αφομοίωση                  strong assimilation

The wiki labels are not written exactly like the expert list (e.g. the wiki has
``Αναφορές στους αδρανείς ‘άλλους’`` and the expert list has ``Αναφορές στους/στις
αδρανείς Άλλους/ες``). So each indicator is matched by a short, distinctive key
phrase after normalisation (lower case, no accents, no quotes).
"""

from __future__ import annotations

import re
import unicodedata

DISCRIMINATION = "Διάκριση"
ASSIMILATION = "Αφομοίωση"

OTHER_AS_PROBLEM = "Ο/Η Άλλος/η ως πρόβλημα"
DISTANT_OTHER = "Ο/Η απομακρυσμένος/η Άλλος/η"
PASSIVE_OTHER = "Ο/Η παθητικός/η Άλλος/η"
WEAK_ASSIMILATION = "Ασθενής αφομοίωση"
STRONG_ASSIMILATION = "Ισχυρή αφομοίωση"

# (category, key phrase found in the normalised indicator, broader subcategory).
# Key phrases are normalised the same way as the indicators (see normalize()).
INDICATOR_RULES: list[tuple[str, str, str]] = [
    # Διάκριση
    (DISCRIMINATION, "ως προβλημα", OTHER_AS_PROBLEM),              # ... Άλλους/ες ως πρόβλημα
    (DISCRIMINATION, "παρανομ", OTHER_AS_PROBLEM),                  # ... παράνομους/ες ή/και νόμιμους/ες ...
    (DISCRIMINATION, "ανωνυμ", DISTANT_OTHER),                      # ... ανώνυμους/ες Άλλους/ες
    (DISCRIMINATION, "προσωριν", DISTANT_OTHER),                    # ... προσωρινούς/ές Άλλους/ες
    (DISCRIMINATION, "αδραν", PASSIVE_OTHER),                       # ... αδρανείς Άλλους/ες
    (DISCRIMINATION, "ως θυματα", PASSIVE_OTHER),                   # ... Άλλους/ες ως θύματα
    (DISCRIMINATION, "αποδεκτ", PASSIVE_OTHER),                     # ... ως αποδέκτες/τριες βοήθειας
    # Αφομοίωση
    (ASSIMILATION, "πρακτικες ενταξης", WEAK_ASSIMILATION),         # ... πρακτικές ένταξης/ενσωμάτωσης
    (ASSIMILATION, "μετριασμεν", WEAK_ASSIMILATION),                # ... μετριασμένους τρόπους αντίκρουσης ...
    (ASSIMILATION, "εκμαθησης ελληνικων", STRONG_ASSIMILATION),     # ... πρακτικές εκμάθησης ελληνικών
    (ASSIMILATION, "θετικη σταση", STRONG_ASSIMILATION),            # ... θετική στάση ... αφομοιωτικές πρακτικές
]

# Order in which subcategories are listed in the output.
SUBCATEGORY_ORDER = [
    OTHER_AS_PROBLEM, DISTANT_OTHER, PASSIVE_OTHER, WEAK_ASSIMILATION, STRONG_ASSIMILATION,
]


def normalize(text: str) -> str:
    """Lower-case, strip accents and quote marks, collapse whitespace."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[‘’'\"«»“”]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def broader_subcategory(category: str, indicator: str) -> str | None:
    """Return the broader subcategory of one indicator, or None if unknown."""
    norm_indicator = normalize(indicator)
    norm_category = normalize(category)
    for rule_category, key, subcategory in INDICATOR_RULES:
        if normalize(rule_category) == norm_category and normalize(key) in norm_indicator:
            return subcategory
    return None


def map_racism_structure(
    racism_structure: dict[str, list[str]],
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Map ``{category: [indicators]}`` to ``{category: [broader subcategories]}``.

    Returns the mapping and the list of ``(category, indicator)`` pairs that no
    rule matched, so callers can report them instead of losing them silently.
    """
    result: dict[str, list[str]] = {}
    unmapped: list[tuple[str, str]] = []
    for category, indicators in (racism_structure or {}).items():
        found = set()
        for indicator in indicators:
            subcategory = broader_subcategory(category, indicator)
            if subcategory is None:
                unmapped.append((category, indicator))
            else:
                found.add(subcategory)
        result[category] = [s for s in SUBCATEGORY_ORDER if s in found]
    return result, unmapped
