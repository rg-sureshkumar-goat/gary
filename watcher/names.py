"""Which form of a name to put in which box.

A person can have three names on one application: the legal one, the one they
go by, and whatever a plain "First Name" box should hold. Which is wanted
depends on the form as a whole, not just the field in front of you:

  * a field that says **legal** always takes the legal name
  * a field that says **preferred** always takes the preferred one
  * a plain "First Name" is ambiguous. If the form offers a preferred-name
    section elsewhere, the plain box is the legal one and the preferred name
    goes in its own field. If it doesn't, the plain box is the name you go by.

So the plain fields cannot be answered until the whole form has been read.
"""
import re

LEGAL = re.compile(r"\blegal\b", re.I)
PREFERRED = re.compile(r"\bpreferred\b|\bgoes?\s+by\b|\bnickname\b|"
                       r"\bknown\s+as\b|\bchosen\s+name\b", re.I)
FIRST = re.compile(r"\bfirst\b|\bgiven\b|\bforename\b", re.I)
LAST = re.compile(r"\blast\b|\bsurname\b|\bfamily\b", re.I)
FULL = re.compile(r"\bfull\s+name\b|^name$|\bname\b", re.I)

# A checkbox that reveals the preferred-name boxes.
PREFERRED_TOGGLE = re.compile(
    r"preferred\s+name|different\s+name|another\s+name|go\s+by\s+a\s+different",
    re.I)


def is_name_field(label):
    return bool(FIRST.search(label or "") or LAST.search(label or "")
                or FULL.search(label or ""))


def form_offers_preferred(labels):
    """Does this form have somewhere to put a preferred name?"""
    return any(PREFERRED.search(str(l or "")) for l in labels)


def form_uses_legal(labels):
    """Does this form ask for a legal name explicitly?"""
    return any(LEGAL.search(str(l or "")) for l in labels)


def is_preferred_toggle(label):
    """A control that reveals the preferred-name fields."""
    return bool(PREFERRED_TOGGLE.search(str(label or "")))


def name_for(label, profile, labels_on_form=()):
    """The value for a name field, or None if this is not one.

    `labels_on_form` is every label on the form, because a plain "First Name"
    means different things depending on whether a preferred-name field exists
    elsewhere.
    """
    text = " ".join(str(label or "").split())
    if not text or not is_name_field(text):
        return None

    legal_first = profile.get("legal_first_name") or profile.get("first_name")
    legal_last = profile.get("legal_last_name") or profile.get("last_name")
    known_first = profile.get("preferred_first_name") or profile.get("first_name")
    known_last = profile.get("preferred_last_name") or profile.get("last_name")

    explicit_legal = bool(LEGAL.search(text))
    explicit_preferred = bool(PREFERRED.search(text))

    if explicit_legal:
        if LAST.search(text):
            return legal_last
        if FIRST.search(text):
            return legal_first
        return " ".join(p for p in (legal_first, legal_last) if p) or None

    if explicit_preferred:
        if LAST.search(text):
            return known_last
        if FIRST.search(text):
            return known_first
        # A single "preferred name" box wants both parts.
        return profile.get("preferred_name") or \
            " ".join(p for p in (known_first, known_last) if p) or None

    # A plain field. If the form has somewhere else for the preferred name,
    # this box is the legal one; otherwise it is the name they go by.
    use_legal = form_offers_preferred(labels_on_form)
    first = legal_first if use_legal else known_first
    last = legal_last if use_legal else known_last

    if LAST.search(text):
        return last
    if FIRST.search(text):
        return first
    return " ".join(p for p in (first, last) if p) or None
