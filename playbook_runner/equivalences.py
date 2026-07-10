"""Conservative option-equivalence matching for application forms.

The playbooks should be able to use ordinary, human-friendly values such as
``TX`` or ``Female`` even when a live form says ``Texas`` or ``F``.  This module
keeps that translation deterministic and bounded: exact matches win first,
then a small set of context-aware aliases is tried.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable


@dataclass(frozen=True)
class OptionCandidate:
    label: str
    value: str | None = None
    index: int = 0


@dataclass(frozen=True)
class OptionMatch:
    candidate: OptionCandidate
    score: int
    reason: str


@dataclass(frozen=True)
class _SalaryRange:
    lower: float | None = None
    upper: float | None = None

    def contains(self, amount: float) -> bool:
        if self.lower is not None and amount < self.lower:
            return False
        if self.upper is not None and amount > self.upper:
            return False
        return self.lower is not None or self.upper is not None

    def distance(self, amount: float) -> float:
        if self.contains(amount):
            return 0.0
        if self.lower is not None and amount < self.lower:
            return self.lower - amount
        if self.upper is not None and amount > self.upper:
            return amount - self.upper
        return float("inf")


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SALARY_AMOUNT_RE = re.compile(
    r"(?<![a-z0-9])(?:[$€£]\s*)?(\d+(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*([kK]))?"
)
_DEFAULT_CUSTOM_EQUIVALENCES_PATH = (
    Path(__file__).resolve().parent.parent / "information" / "custom_equivalences.json"
)
_CUSTOM_EQUIVALENCES_PATH = Path(
    os.environ.get("PLAYBOOK_CUSTOM_EQUIVALENCES") or _DEFAULT_CUSTOM_EQUIVALENCES_PATH
)


def normalize(value: Any) -> str:
    """Normalize labels for comparison without losing semantic words."""
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    text = text.replace("'", "")
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def compact(value: Any) -> str:
    return normalize(value).replace(" ", "")


def _aliases(*items: str) -> set[str]:
    return {normalize(item) for item in items if normalize(item)}


def _alias_map(groups: dict[str, Iterable[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in groups.items():
        key = normalize(canonical)
        out[key] = key
        for alias in aliases:
            out[normalize(alias)] = key
    return out


_YES_NO = _alias_map({
    "yes": ["y", "true", "1"],
    "no": ["n", "false", "0"],
})

_DECLINE = _alias_map({
    "decline": [
        "decline",
        "declined",
        "i decline",
        "decline to answer",
        "decline to self identify",
        "decline to self-identify",
        "i decline to answer",
        "i decline to self identify",
        "i decline to self-identify",
        "prefer not to say",
        "prefer not to answer",
        "prefer not to disclose",
        "i prefer not to answer",
        "i prefer not to disclose",
        "i do not wish to answer",
        "i don't wish to answer",
        "i dont wish to answer",
        "i do not wish to provide",
        "i do not wish to provide this information",
        "i do not wish to self identify",
        "i do not wish to self-identify",
        "i dont wish to provide this information",
        "i do not want to answer",
        "i do not want to disclose",
        "choose not to disclose",
        "choose not to answer",
        "i choose not to disclose",
        "i choose not to answer",
        "i choose not to self identify",
        "i choose not to self-identify",
        "do not wish to disclose",
        "not disclosed",
        "not specified",
        "not provided",
        "not applicable",
        "n a",
        "na",
        "undisclosed",
        "no answer",
        "unknown",
    ],
})

_GENDER = _alias_map({
    "male": ["m", "man", "male man", "man male"],
    "female": ["f", "woman", "female woman", "woman female"],
    "nonbinary": [
        "non binary",
        "non-binary",
        "nonbinary",
        "non binary gender",
        "non-binary gender",
        "gender nonconforming",
        "gender non conforming",
        "genderqueer",
        "agender",
        "another gender",
        "other",
        "x",
        "self describe",
        "self-described",
    ],
})

_PRONOUNS = _alias_map({
    "he him": ["he/him"],
    "she her": ["she/her"],
    "they them": ["they/them"],
    "ze hir": ["ze/hir"],
    "ze zir": ["ze/zir"],
})

_PHONE = _alias_map({
    "mobile": ["mobile phone", "cell", "cell phone", "cellular", "cellular phone"],
    "home": ["home phone"],
    "work": ["work phone", "business", "business phone", "office", "office phone"],
})

_DEGREE = _alias_map({
    "doctorate": [
        "phd",
        "ph d",
        "ph.d",
        "ph.d.",
        "ph d doctor of philosophy",
        "phd doctor of philosophy",
        "ph d doctorate",
        "phd doctorate",
        "doctor of philosophy",
        "doctor of philosophy ph d",
        "doctor of philosophy phd",
        "doctoral",
        "doctoral degree",
        "doctorate academic",
        "doctorate degree",
        "doctorate",
        "post doctorate",
        "post doctoral",
        "postdoctoral",
        "post graduate degree",
        "postgraduate degree",
        "graduate degree",
        "edd",
        "ed d",
        "doctor of education",
        "dba",
        "doctor of business administration",
        "drph",
        "dr ph",
        "doctor of public health",
        "doctorate academic",
        "academic doctorate",
        "j doctorate academic",
    ],
    "masters": [
        "master",
        "masters",
        "masters degree",
        "master degree",
        "graduate masters",
        "graduate master's",
        "m s",
        "ms",
        "msc",
        "m sc",
        "master of science",
        "m a",
        "ma",
        "master of arts",
        "mba",
        "m b a",
        "master of business administration",
        "mfa",
        "m f a",
        "master of fine arts",
        "mph",
        "m p h",
        "master of public health",
        "masters level degree",
        "i masters level degree",
    ],
    "bachelors": [
        "bachelor",
        "bachelors",
        "bachelors degree",
        "bachelor degree",
        "4 year university college degree",
        "four year university college degree",
        "bachelors level degree",
        "b s",
        "bs",
        "bsc",
        "b sc",
        "bachelor of science",
        "b a",
        "ba",
        "bachelor of arts",
        "bba",
        "b b a",
        "bachelor of business administration",
        "bachelors level degree",
        "g bachelors level degree",
    ],
    "associate": [
        "associates",
        "associate degree",
        "2 year college degree",
        "two year college degree",
        "aa",
        "a a",
        "as",
        "a s",
        "2 year college degree",
        "f 2 year college degree",
    ],
    "high school": [
        "high school",
        "high school diploma",
        "ged",
        "g e d",
        "secondary school",
        "secondary education",
        "hs graduate or equivalent",
        "high school graduate or equivalent",
        "c hs graduate or equivalent",
    ],
    "less than high school": [
        "less than high school",
        "less than hs graduate",
        "b less than hs graduate",
    ],
    "some college": [
        "some college",
        "d some college",
    ],
    "technical school": [
        "technical school",
        "trade school",
        "vocational school",
        "e technical school",
    ],
    "some graduate school": [
        "some graduate school",
        "h some graduate school",
    ],
    "professional degree": [
        "professional degree",
        "professional doctorate",
        "doctorate professional",
        "k doctorate professional",
    ],
    "juris doctor": ["jd", "j d", "juris doctor"],
    "medical doctor": ["md", "m d", "doctor of medicine"],
})

_RACE_ETHNICITY = _alias_map({
    "asian": ["asian", "asian not hispanic or latino", "asian not hispanic"],
    "white": ["white", "caucasian", "white not hispanic or latino", "white not hispanic"],
    "black": [
        "black",
        "african american",
        "black african american",
        "black or african american",
        "black not hispanic or latino",
    ],
    "american indian": [
        "american indian",
        "alaska native",
        "american indian or alaska native",
        "american indian alaska native",
        "native american",
    ],
    "pacific islander": [
        "native hawaiian",
        "pacific islander",
        "native hawaiian or other pacific islander",
        "native hawaiian other pacific islander",
    ],
    "two or more races": [
        "two or more",
        "two or more races",
        "multiple races",
        "multiracial",
        "multi racial",
    ],
    "hispanic": ["hispanic", "latino", "latina", "latinx", "hispanic or latino"],
    "not hispanic": [
        "not hispanic",
        "not latino",
        "not hispanic or latino",
        "not hispanic latino",
    ],
})

_VETERAN = _alias_map({
    "protected veteran": [
        "protected veteran",
        "i am a protected veteran",
        "yes i am a protected veteran",
        "other protected veteran",
        "disabled veteran",
        "recently separated veteran",
        "active duty wartime or campaign badge veteran",
        "active wartime or campaign badge veteran",
        "armed forces service medal veteran",
        "special disabled veteran",
        "vietnam era veteran",
    ],
    "not protected veteran": [
        "not a protected veteran",
        "i am not a protected veteran",
        "no i am not a protected veteran",
        "i am not a veteran",
        "not a veteran",
        "not an other protected veteran",
        "not other protected veteran",
        "not a protected veteran i identify as one or more",
    ],
})

_DISABILITY = _alias_map({
    "has disability": [
        "yes",
        "disabled",
        "has disability",
        "have a disability",
        "i have a disability",
        "yes i have a disability",
        "yes i have a disability or have had one in the past",
        "yes i have a disability or previously had one",
    ],
    "no disability": [
        "no",
        "not disabled",
        "does not have disability",
        "do not have a disability",
        "i do not have a disability",
        "no i do not have a disability",
        "no i do not have a disability and have not had one in the past",
        "no i do not have a disability or have not had one in the past",
    ],
})

_WORK_AUTH = _alias_map({
    "authorized": [
        "yes",
        "true",
        "authorized",
        "work authorized",
        "authorized to work",
        "legally authorized to work",
        "i am authorized to work",
        "i am currently authorized to work",
        "i am legally authorized to work",
        "i am authorized to work in the united states",
        "i am currently authorized to work in the united states",
        "i am legally authorized to work in the united states",
        "yes i am currently authorized to work in the united states",
        "yes i am authorized to work in the united states",
        "us citizen",
        "u s citizen",
        "citizen",
        "permanent resident",
        "green card",
    ],
    "not authorized": [
        "no",
        "false",
        "not authorized",
        "not work authorized",
        "not legally authorized",
        "not authorized to work",
        "i am not authorized to work",
        "i am not currently authorized to work",
        "i am not authorized to work in the united states",
        "i am not currently authorized to work in the united states",
        "no i am not authorized to work in the united states",
    ],
})

_SPONSORSHIP = _alias_map({
    "requires sponsorship": [
        "yes",
        "true",
        "requires sponsorship",
        "require sponsorship",
        "need sponsorship",
        "needs sponsorship",
        "will require sponsorship",
        "now or in the future require sponsorship",
        "h1b",
        "h 1b",
        "h-1b",
        "visa sponsorship required",
        "stem opt support",
    ],
    "no sponsorship": [
        "no",
        "false",
        "does not require sponsorship",
        "do not require sponsorship",
        "doesnt require sponsorship",
        "will not require sponsorship",
        "i do not require sponsorship",
        "i do not require visa sponsorship",
        "i will not require visa sponsorship",
        "no sponsorship",
        "visa sponsorship not required",
        "not now or in the future",
    ],
})

_CITIZENSHIP_STATUS = _alias_map({
    "citizen": [
        "citizen",
        "us citizen",
        "u s citizen",
        "u.s. citizen",
        "united states citizen",
        "1 citizen",
    ],
    "permanent resident": [
        "permanent resident",
        "lawful permanent resident",
        "legal permanent resident",
        "green card",
        "green card holder",
        "5 permanent resident",
    ],
    "alien authorized to work": [
        "alien authorized to work",
        "authorized to work",
        "work authorized",
        "employment authorized",
        "employment authorization",
        "ead",
        "f 1 opt",
        "f-1 opt",
        "opt",
        "stem opt",
        "h 1b",
        "h-1b",
        "tn",
        "j 1",
        "j-1",
        "other",
        "4 alien authorized to work",
    ],
    "noncitizen national": [
        "noncitizen national",
        "non citizen national",
        "non-citizen national",
        "noncitizen national of the united states",
        "non citizen national of the united states",
        "8 noncitizen national of the united states",
    ],
})

_EDUCATION_STATUS = _alias_map({
    "completed": [
        "completed",
        "complete",
        "graduated",
        "degree awarded",
        "awarded",
        "received",
        "conferred",
    ],
    "in progress": [
        "in progress",
        "current",
        "currently enrolled",
        "enrolled",
        "pursuing",
        "expected",
        "not completed",
    ],
})

_EMPLOYMENT_STATUS = _alias_map({
    "full time": ["full time", "full-time", "ft", "f t"],
    "part time": ["part time", "part-time", "pt", "p t"],
    "temporary": ["temporary", "temp", "fixed term", "fixed-term"],
    "permanent": ["permanent", "regular"],
    "contract": ["contract", "contractor", "consultant"],
    "internship": ["internship", "intern"],
    "postdoc": ["postdoc", "post doc", "post-doc", "postdoctoral", "post doctoral"],
    "tenure track": ["tenure track", "tenure-track", "tenure eligible"],
    "non tenure track": ["non tenure track", "non-tenure track", "non tenure"],
})

_REFERRAL = _alias_map({
    "job board": [
        "job board",
        "job posting board",
        "web based job posting board",
        "online job board",
        "internet job board",
    ],
    "employer website": [
        "company website",
        "employer website",
        "career site",
        "careers site",
        "organization website",
        "university website",
        "institution website",
    ],
    "employee referral": [
        "employee referral",
        "referred by employee",
        "current employee",
        "friend",
        "colleague",
        "peer",
    ],
    "professional organization": [
        "professional organization",
        "professional association",
        "academic organization",
        "professional or academic organization",
        "association",
    ],
    "search firm": ["search firm", "recruiter", "headhunter", "agency"],
    "social media": ["social media", "social network", "facebook", "twitter", "x"],
    "linkedin": ["linkedin", "linked in"],
    "indeed": ["indeed"],
    "higheredjobs": ["higheredjobs", "higher ed jobs", "higher education jobs"],
    "herc": ["herc", "higher education recruitment consortium"],
    "chronicle": ["chronicle", "chronicle of higher education"],
    "mathjobs": ["mathjobs", "math jobs"],
})

_SALARY_PERIOD = _alias_map({
    "annual": ["annual", "annually", "year", "yearly", "per year", "salary"],
    "hourly": ["hourly", "hour", "per hour"],
    "monthly": ["monthly", "month", "per month"],
    "weekly": ["weekly", "week", "per week"],
})

_US_STATES_RAW = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE = _alias_map({name: [abbr, name] for abbr, name in _US_STATES_RAW.items()})

_US_TERRITORIES_RAW = {
    "AS": "American Samoa",
    "FM": "Federated States of Micronesia",
    "GU": "Guam",
    "MH": "Marshall Islands",
    "MP": "Northern Mariana Islands",
    "PW": "Palau",
    "PR": "Puerto Rico",
    "VI": "United States Virgin Islands",
}
_STATE.update(_alias_map({
    name: [abbr, name, name.replace("United States", "US"), name.replace("United States", "U.S.")]
    for abbr, name in _US_TERRITORIES_RAW.items()
}))

_MILITARY_STATE_CODES_RAW = {
    "AA": "Armed Forces Americas",
    "AE": "Armed Forces Europe",
    "AP": "Armed Forces Pacific",
}
_STATE.update(_alias_map({
    name: [abbr, name, name.replace("Armed Forces", "Military")]
    for abbr, name in _MILITARY_STATE_CODES_RAW.items()
}))

_COUNTRY = _alias_map({
    "united states": [
        "united states",
        "united states of america",
        "usa",
        "u s a",
        "us",
        "u s",
        "america",
    ],
    "united kingdom": ["united kingdom", "uk", "u k", "great britain", "britain"],
    "england": ["england"],
    "scotland": ["scotland"],
    "wales": ["wales"],
    "ireland": ["ireland", "republic of ireland"],
    "china": ["china", "peoples republic of china", "prc"],
    "hong kong": ["hong kong", "hong kong sar"],
    "taiwan": ["taiwan", "republic of china"],
    "canada": ["canada"],
    "mexico": ["mexico"],
    "india": ["india", "bharat"],
    "australia": ["australia"],
    "new zealand": ["new zealand", "nz", "n z"],
    "japan": ["japan"],
    "south korea": ["south korea", "korea republic of", "republic of korea"],
    "germany": ["germany", "deutschland"],
    "france": ["france"],
    "spain": ["spain"],
    "italy": ["italy"],
    "netherlands": ["netherlands", "the netherlands", "holland"],
    "belgium": ["belgium"],
    "switzerland": ["switzerland"],
    "sweden": ["sweden"],
    "norway": ["norway"],
    "denmark": ["denmark"],
    "finland": ["finland"],
    "brazil": ["brazil", "brasil"],
    "argentina": ["argentina"],
    "chile": ["chile"],
    "colombia": ["colombia"],
    "peru": ["peru"],
    "south africa": ["south africa"],
    "nigeria": ["nigeria"],
    "egypt": ["egypt"],
    "israel": ["israel"],
    "turkey": ["turkey", "turkiye"],
    "singapore": ["singapore"],
    "malaysia": ["malaysia"],
    "indonesia": ["indonesia"],
    "philippines": ["philippines"],
    "vietnam": ["vietnam", "viet nam"],
    "thailand": ["thailand"],
    "russia": ["russia", "russian federation"],
    "ukraine": ["ukraine"],
})
_COUNTRY.update(_alias_map({
    "bahamas": ["bahama", "the bahamas"],
    "brunei": ["brunei", "brunei darussalam"],
    "myanmar": ["burma", "burma no longer exists"],
    "ivory coast": [
        "cote divoire",
        "côte divoire",
        "cote d ivoire",
        "côte d ivoire",
        "cote d'ivoire",
        "côte d'ivoire",
        "ivory coast",
        "côte divoire ivory coast",
    ],
    "czech republic": ["czech republic", "czechia"],
    "east timor": ["east timor", "timor leste"],
    "iran": ["iran", "islamic republic of iran", "iran islamic republic of"],
    "north korea": [
        "north korea",
        "korea democratic peoples republic of",
        "democratic peoples republic of korea",
    ],
    "south korea": ["south korea", "korea republic of", "republic of korea"],
    "laos": ["laos", "lao peoples democratic republic"],
    "libya": ["libya", "libyan arab jamahiriya"],
    "macau": ["macau", "macao"],
    "moldova": ["moldova", "moldova republic of", "republic of moldova"],
    "palestine": [
        "palestine",
        "palestinian territory",
        "palestinian territory occupied",
        "occupied palestinian territory",
    ],
    "democratic republic of the congo": [
        "democratic republic of the congo",
        "congo democratic republic of the",
        "congo dr",
        "drc",
    ],
    "republic of the congo": ["republic of the congo", "congo"],
    "north macedonia": [
        "north macedonia",
        "north macedonia republic of",
        "former yugoslav republic of macedonia",
    ],
    "montenegro": ["montenegro", "montenegro republic of"],
    "serbia": ["serbia", "serbia republic of"],
    "sint maarten": ["sint maarten", "sint maarten dutch", "saint martin dutch"],
    "saint barthelemy": ["saint barthelemy", "st barthelemy", "st barthélemy"],
    "saint helena": ["saint helena", "st helena"],
    "saint kitts and nevis": ["saint kitts and nevis", "st kitts and nevis"],
    "saint pierre and miquelon": [
        "saint pierre and miquelon",
        "st pierre and miquelon",
        "st pierre and miquelon",
    ],
    "saint vincent and the grenadines": [
        "saint vincent and the grenadines",
        "st vincent and the grenadines",
    ],
    "saint martin": ["saint martin", "st martin", "st martin french"],
    "sao tome and principe": ["sao tome and principe", "sao tome principe"],
    "eswatini": ["eswatini", "swaziland"],
    "syria": ["syria", "syrian arab republic"],
    "tanzania": ["tanzania", "tanzania united republic of"],
    "united kingdom": [
        "united kingdom great britain",
        "united kingdom",
        "great britain",
        "uk",
        "u k",
    ],
    "united states virgin islands": [
        "united states virgin islands",
        "us virgin islands",
        "u s virgin islands",
    ],
    "vatican city": ["vatican city", "vatican city state holy see", "holy see"],
    "venezuela": ["venezuela", "venezuela bolivarian republic of"],
    "vietnam": ["vietnam", "viet nam"],
}))

_CANADIAN_PROVINCES_RAW = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}
_STATE.update(_alias_map({
    name: [abbr, name, name.replace("and", "&")]
    for abbr, name in _CANADIAN_PROVINCES_RAW.items()
}))
_STATE.update(_alias_map({
    "Newfoundland and Labrador": [
        "NF",
        "Newfoundland",
        "Newfoundland and Labrador",
        "Newfoundland & Labrador",
    ]
}))

_GROUPS = {
    "yes_no": _YES_NO,
    "decline": _DECLINE,
    "gender": _GENDER,
    "pronouns": _PRONOUNS,
    "phone": _PHONE,
    "degree": _DEGREE,
    "race_ethnicity": _RACE_ETHNICITY,
    "veteran": _VETERAN,
    "disability": _DISABILITY,
    "work_auth": _WORK_AUTH,
    "sponsorship": _SPONSORSHIP,
    "citizenship_status": _CITIZENSHIP_STATUS,
    "education_status": _EDUCATION_STATUS,
    "employment_status": _EMPLOYMENT_STATUS,
    "referral": _REFERRAL,
    "salary_period": _SALARY_PERIOD,
    "state": _STATE,
    "country": _COUNTRY,
}

_GROUP_SCORES = {
    "state": 96,
    "country": 96,
    "gender": 94,
    "pronouns": 94,
    "degree": 93,
    "phone": 93,
    "race_ethnicity": 92,
    "disability": 92,
    "yes_no": 92,
    "decline": 92,
    "work_auth": 91,
    "sponsorship": 91,
    "citizenship_status": 91,
    "veteran": 90,
    "education_status": 90,
    "employment_status": 90,
    "referral": 88,
    "salary_period": 88,
}

_CONTEXT_HINTS = {
    "state": _aliases("state", "province"),
    "country": _aliases("country", "nation", "nationality"),
    "gender": _aliases("gender", "sex"),
    "pronouns": _aliases("pronoun", "pronouns", "salutation"),
    "degree": _aliases("degree", "education", "highest level", "qualification"),
    "education_status": _aliases("education status", "degree status", "graduation status"),
    "employment_status": _aliases("employment status", "job status", "position status", "appointment"),
    "phone": _aliases("phone", "telephone", "primary number", "number type"),
    "race_ethnicity": _aliases("race", "ethnic", "ethnicity", "hispanic", "latino"),
    "veteran": _aliases("veteran", "military", "armed forces"),
    "disability": _aliases("disability", "disabled", "cc 305", "cc305"),
    "work_auth": _aliases("authorized", "authorization", "work authorization", "eligible to work"),
    "sponsorship": _aliases("sponsor", "sponsorship", "visa", "h1b", "h 1b", "stem opt"),
    "citizenship_status": _aliases(
        "citizenship",
        "citizenship status",
        "citizen status",
        "immigration status",
        "work status",
    ),
    "referral": _aliases("source", "referral", "heard", "how did you hear", "job board"),
    "salary_range": _aliases(
        "salary",
        "desired salary",
        "salary expectation",
        "expected salary",
        "compensation",
        "pay",
        "wage",
        "rate",
    ),
    "salary_period": _aliases("salary period", "pay period", "compensation period", "rate type"),
}


def custom_equivalences_path() -> Path:
    return _CUSTOM_EQUIVALENCES_PATH


def known_equivalence_groups() -> list[str]:
    return sorted(_GROUPS)


def active_groups_for_context(context: str | None) -> list[str]:
    return sorted(_active_groups(context))


def canonical_key_for_group(group: str, value: Any) -> str:
    alias_map = _GROUPS.get(group)
    normalized = normalize(value)
    if not alias_map:
        return normalized
    return alias_map.get(normalized, normalized)


def best_match(
    wanted: Any,
    candidates: Iterable[OptionCandidate | dict[str, Any] | str],
    *,
    context: str | None = None,
    minimum_score: int = 80,
) -> OptionMatch | None:
    """Return the best deterministic match, or ``None`` when unclear.

    ``context`` is the field/question label.  Abbreviation-heavy groups such as
    states and gender are only enabled when the context suggests them, so a
    single-letter value like ``M`` does not get interpreted everywhere.
    """
    wanted_text = "" if wanted is None else str(wanted)
    wanted_norm = normalize(wanted_text)
    if not wanted_norm:
        return None

    options = [_coerce_candidate(item, index) for index, item in enumerate(candidates)]
    active_groups = _active_groups(context)
    scored: list[OptionMatch] = []
    for candidate in options:
        match = _score_candidate(wanted_text, candidate, active_groups)
        if match and match.score >= minimum_score:
            scored.append(match)

    if not scored:
        return None
    scored.sort(key=lambda item: (-item.score, item.candidate.index))
    best = scored[0]
    tied = [
        item for item in scored[1:]
        if item.score == best.score and normalize(item.candidate.label) != normalize(best.candidate.label)
    ]
    if tied and best.score < 100:
        return None
    return best


def candidate_preview(candidates: Iterable[OptionCandidate], limit: int = 10) -> str:
    labels = []
    for candidate in candidates:
        label = candidate.label or candidate.value or ""
        if label:
            labels.append(label)
        if len(labels) >= limit:
            break
    return ", ".join(labels)


def equivalence_gap_report(
    wanted: Any,
    candidates: Iterable[OptionCandidate | dict[str, Any] | str],
    *,
    context: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Build a structured artifact for a failed option-equivalence match."""
    options = [_coerce_candidate(item, index) for index, item in enumerate(candidates)]
    active = sorted(_active_groups(context))
    candidate_rows = []
    for row_index, candidate in enumerate(options[:limit]):
        row = {
            "index": row_index,
            "candidate_index": candidate.index,
            "label": candidate.label,
            "value": candidate.value,
            "label_normalized": normalize(candidate.label),
            "value_normalized": normalize(candidate.value),
        }
        candidate_rows.append(row)
    return {
        "kind": "equivalence_gap",
        "action": action or "",
        "wanted": "" if wanted is None else str(wanted),
        "wanted_normalized": normalize(wanted),
        "context": context or "",
        "context_normalized": normalize(context or ""),
        "active_groups": active,
        "candidate_count": len(options),
        "candidates": candidate_rows,
        "truncated": len(options) > limit,
        "repair_command": (
            "python3 tools/accept_equivalence_gap.py "
            "shots/<site>/error-step-###/equivalence-gap.json "
            "--group <group> --candidate-index <index>"
        ),
    }


def _coerce_candidate(item: OptionCandidate | dict[str, Any] | str, index: int) -> OptionCandidate:
    if isinstance(item, OptionCandidate):
        return item
    if isinstance(item, dict):
        return OptionCandidate(
            label=str(item.get("label") or item.get("text") or item.get("value") or ""),
            value=None if item.get("value") is None else str(item.get("value")),
            index=int(item.get("index", index)),
        )
    return OptionCandidate(label=str(item), value=None, index=index)


def _apply_custom_equivalences(path: Path = _CUSTOM_EQUIVALENCES_PATH) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid custom equivalences JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"custom equivalences file {path} must contain a JSON object")

    groups = data.get("groups", {})
    if groups is None:
        groups = {}
    if not isinstance(groups, dict):
        raise RuntimeError(f"custom equivalences file {path}: 'groups' must be an object")
    for group, entries in groups.items():
        if group not in _GROUPS:
            raise RuntimeError(
                f"custom equivalences file {path}: unknown group {group!r}; "
                f"known groups: {', '.join(sorted(_GROUPS))}"
            )
        if not isinstance(entries, dict):
            raise RuntimeError(
                f"custom equivalences file {path}: group {group!r} must map "
                "canonical values to alias lists"
            )
        _merge_alias_entries(_GROUPS[group], entries)

    hints = data.get("context_hints", {})
    if hints is None:
        hints = {}
    if not isinstance(hints, dict):
        raise RuntimeError(f"custom equivalences file {path}: 'context_hints' must be an object")
    for group, values in hints.items():
        if group not in _CONTEXT_HINTS:
            raise RuntimeError(
                f"custom equivalences file {path}: unknown context-hint group {group!r}; "
                f"known groups: {', '.join(sorted(_CONTEXT_HINTS))}"
            )
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise RuntimeError(
                f"custom equivalences file {path}: context_hints.{group} must be a string list"
            )
        _CONTEXT_HINTS[group].update(_aliases(*values))


def _merge_alias_entries(alias_map: dict[str, str], entries: dict[str, Any]) -> None:
    for canonical, aliases in entries.items():
        canonical_norm = normalize(canonical)
        if not canonical_norm:
            continue
        canonical_key = alias_map.get(canonical_norm, canonical_norm)
        alias_map[canonical_norm] = canonical_key
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
            raise RuntimeError(
                f"custom aliases for {canonical!r} must be a string or string list"
            )
        for alias in aliases:
            alias_norm = normalize(alias)
            if alias_norm:
                alias_map[alias_norm] = canonical_key


def _active_groups(context: str | None) -> set[str]:
    active = {"yes_no", "decline"}
    ctx = normalize(context or "")
    ctx_tokens = set(ctx.split())
    for group, hints in _CONTEXT_HINTS.items():
        if ctx in hints or ctx_tokens.intersection(hints) or any(hint in ctx for hint in hints):
            active.add(group)
    return active


def _score_candidate(
    wanted: str,
    candidate: OptionCandidate,
    active_groups: set[str],
) -> OptionMatch | None:
    best: OptionMatch | None = None
    for source, raw in (("label", candidate.label), ("value", candidate.value)):
        if raw is None:
            continue
        scored = _score_text(wanted, raw, active_groups, source)
        if scored is None:
            continue
        score, reason = scored
        if best is None or score > best.score:
            best = OptionMatch(candidate=candidate, score=score, reason=reason)
    return best


def _score_text(
    wanted: str,
    candidate: str,
    active_groups: set[str],
    source: str,
) -> tuple[int, str] | None:
    want = normalize(wanted)
    cand = normalize(candidate)
    if not want or not cand:
        return None
    if want == cand:
        return 100, f"exact {source}"
    if compact(want) == compact(cand):
        return 99, f"punctuation-insensitive {source}"

    if "salary_range" in active_groups:
        salary_match = _score_salary_range(wanted, candidate, source)
        if salary_match is not None:
            return salary_match

    for group in active_groups:
        if group == "salary_range":
            continue
        want_key = _GROUPS[group].get(want)
        cand_key = _GROUPS[group].get(cand)
        if want_key and cand_key and want_key == cand_key:
            return _GROUP_SCORES[group], f"{group} alias"

    if "country" in active_groups:
        country_code_match = _score_country_code_label(wanted, candidate, source)
        if country_code_match is not None:
            return country_code_match

    if "degree" in active_groups:
        degree_code_match = _score_degree_code_label(wanted, candidate, source)
        if degree_code_match is not None:
            return degree_code_match

    if _is_yes_no_prefix(want, cand):
        return 88, f"yes/no prefix {source}"
    if "veteran" in active_groups and _is_veteran_negative(want, cand):
        return 88, f"veteran negative {source}"
    if "citizenship_status" in active_groups and _is_citizenship_status_mismatch(want, cand):
        return None

    if len(want) >= 4 and (cand.startswith(want) or want.startswith(cand)):
        return 84, f"prefix {source}"
    if len(want) >= 5 and (want in cand or cand in want):
        return 80, f"contains {source}"
    if len(want) >= 5 and _token_subset(want, cand):
        return 80, f"token subset {source}"
    return None


def _score_country_code_label(wanted: str, candidate: str, source: str) -> tuple[int, str] | None:
    match = re.match(r"^\s*([A-Za-z]{2,4})\s*[-–]\s*(.+?)\s*$", candidate)
    if not match:
        return None

    code = normalize(match.group(1))
    label = normalize(match.group(2))
    want = normalize(wanted)
    if not want or not label:
        return None

    if want == code:
        return 97, f"country code-prefix {source}"
    if want == label or compact(want) == compact(label):
        return 97, f"country label-prefix {source}"

    want_key = _COUNTRY.get(want)
    label_key = _COUNTRY.get(label)
    if want_key and label_key and want_key == label_key:
        return 96, f"country label-prefix alias {source}"

    if len(want) >= 5 and (label.startswith(want) or want.startswith(label)):
        return 86, f"country label-prefix prefix {source}"
    if len(want) >= 5 and (want in label or label in want):
        return 85, f"country label-prefix contains {source}"
    return None


def _score_degree_code_label(wanted: str, candidate: str, source: str) -> tuple[int, str] | None:
    match = re.match(r"^\s*([A-Za-z])\s*[-–]\s*(.+?)\s*$", candidate)
    if not match:
        return None

    label = normalize(match.group(2))
    want = normalize(wanted)
    if not want or not label:
        return None

    if want == label or compact(want) == compact(label):
        return 97, f"degree label-prefix {source}"

    want_key = _DEGREE.get(want)
    label_key = _DEGREE.get(label)
    if want_key and label_key and want_key == label_key:
        if "post doctorate" in label and "post" not in want:
            return 89, f"degree label-prefix post-doctorate fallback {source}"
        return 93, f"degree label-prefix alias {source}"

    if len(want) >= 5 and (label.startswith(want) or want.startswith(label)):
        return 86, f"degree label-prefix prefix {source}"
    if len(want) >= 5 and (want in label or label in want):
        return 85, f"degree label-prefix contains {source}"
    return None


def _is_yes_no_prefix(want: str, cand: str) -> bool:
    want_key = _YES_NO.get(want)
    if want_key == "yes":
        return cand == "yes" or cand.startswith("yes ")
    if want_key == "no":
        return cand == "no" or cand.startswith("no ")
    return False


def _is_veteran_negative(want: str, cand: str) -> bool:
    want_key = _YES_NO.get(want) or _VETERAN.get(want)
    cand_key = _VETERAN.get(cand)
    return want_key in {"no", "not protected veteran"} and cand_key == "not protected veteran"


def _is_citizenship_status_mismatch(want: str, cand: str) -> bool:
    want_key = _CITIZENSHIP_STATUS.get(want)
    cand_key = _CITIZENSHIP_STATUS.get(cand)
    if not want_key or not cand_key:
        return False
    return want_key != cand_key


def _score_salary_range(wanted: str, candidate: str, source: str) -> tuple[int, str] | None:
    amount = _parse_salary_amount(wanted)
    if amount is None:
        return None

    salary_range = _parse_salary_range(candidate)
    if salary_range is None:
        return None

    if salary_range.contains(amount):
        return 89, f"salary range {source}"

    distance = salary_range.distance(amount)
    if _is_close_salary_boundary(amount, distance):
        return 81, f"nearest salary range {source}"
    return None


def _parse_salary_amount(value: Any) -> float | None:
    amounts = _salary_amounts(str(value))
    if not amounts:
        return None
    return amounts[0]


def _parse_salary_range(value: str) -> _SalaryRange | None:
    text = str(value)
    norm = normalize(text)
    amounts = _salary_amounts(text)
    if not amounts:
        return None

    if len(amounts) >= 2:
        first, second = amounts[0], amounts[1]
        return _SalaryRange(lower=min(first, second), upper=max(first, second))

    amount = amounts[0]
    if _has_upper_bound_word(norm):
        return _SalaryRange(upper=amount)
    if _has_lower_bound_word(norm) or "+" in text:
        return _SalaryRange(lower=amount)
    return None


def _salary_amounts(value: str) -> list[float]:
    raw: list[tuple[float, bool]] = []
    for match in _SALARY_AMOUNT_RE.finditer(value):
        number = match.group(1).replace(",", "").replace(" ", "")
        try:
            amount = float(number)
        except ValueError:
            continue
        raw.append((amount, bool(match.group(2))))

    if not raw:
        return []

    any_k = any(has_k for _, has_k in raw)
    amounts: list[float] = []
    for amount, has_k in raw:
        if has_k or (any_k and amount < 1000):
            amount *= 1000
        amounts.append(amount)
    return amounts


def _has_upper_bound_word(norm: str) -> bool:
    return (
        norm.startswith(("under ", "below "))
        or " less than " in f" {norm} "
        or " no more than " in f" {norm} "
        or " up to " in f" {norm} "
        or norm.endswith((" or less", " and under", " and below"))
        or norm.startswith(("maximum ", "max "))
    )


def _has_lower_bound_word(norm: str) -> bool:
    return (
        norm.startswith(("over ", "above "))
        or " more than " in f" {norm} "
        or " greater than " in f" {norm} "
        or " at least " in f" {norm} "
        or norm.endswith((" or more", " and over", " and above"))
        or norm.startswith(("minimum ", "min "))
    )


def _is_close_salary_boundary(amount: float, distance: float) -> bool:
    if amount <= 0 or distance == float("inf"):
        return False
    return distance <= max(5000.0, amount * 0.10)


def _token_subset(want: str, cand: str) -> bool:
    want_tokens = set(want.split())
    cand_tokens = set(cand.split())
    if len(want_tokens) < 2:
        return False
    return want_tokens <= cand_tokens or cand_tokens <= want_tokens


_apply_custom_equivalences()
