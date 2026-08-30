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

# Field ids are camelCase or snake_case -- legalNameSection_firstName -- so a
# word-boundary match never fires inside them.
ID_LEGAL = re.compile(r"legal", re.I)
ID_PREFERRED = re.compile(r"prefer", re.I)

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


# A name that is not the candidate's. A form asks for plenty of them, and
# every one contains the word "name" -- a relative who works at the company, a
# reference, a supervisor, an emergency contact. Answering any of them with
# the candidate's own name is worse than leaving them blank, because it reads
# as an answer.
_MIDDLE = re.compile(r"middle\s*(?:name|initial)|\bmi\b", re.I)

_SOMEONE_ELSE = re.compile(
    r"relative|family\s+member|spouse|sibling|\bparent\b|next\s+of\s+kin|"
    r"emergency\s+contact|\breference\b|referred\s+by|referrer|"
    r"supervisor|manager|employer\s+name|company\s+name|school\s+name|"
    r"university\s+name|contact\s+name|guardian|beneficiary|"
    r"person\s+who|their\s+name|his\s+name|her\s+name", re.I)


def about_someone_else(label, section=""):
    """Is this asking for a name other than the candidate's?"""
    return bool(_SOMEONE_ELSE.search("%s %s" % (label or "", section or "")))


def name_for(label, profile, labels_on_form=(), section="", identity="",
             preferred_on_form=None):
    """The value for a name field, or None if this is not one.

    Three sources of evidence, most reliable first:

      1. the field's own id. Workday names these exactly --
         legalNameSection_firstName against preferredNameSection_firstName --
         and that settles it.
      2. the label, or the heading the field sits under.
      3. the form as a whole: a plain "First Name" is the legal name when a
         preferred-name block exists elsewhere, and the name you go by when
         it doesn't.

    Evidence 1 matters because a form can label both blocks identically, with
    only the ids and the headings telling them apart -- so reading the label
    alone puts the legal name in the preferred boxes.
    """
    # Workday ids every name field legalName, whether or not the form asks
    # for a legal name at all. So the id only distinguishes anything when a
    # preferred name is also being asked for; on a form with one set of name
    # boxes it says nothing, and the candidate wants the name he goes by.
    if preferred_on_form is False:
        identity = ""
        section = re.sub(r"legal", " ", str(section or ""), flags=re.I)

    # A middle name is its own field, not the whole name. Every name box
    # contains the word "name", and answering this one as though it were
    # unqualified put the candidate's full legal name into it -- which on a
    # form that already asks for first and last reads as a mistake by them.
    if _MIDDLE.search(str(label or "")):
        held = profile.get("middle_name") or profile.get("middle_initial")
        if not held:
            return None
        held = str(held).strip()
        if re.search(r"initial", str(label), re.I) and held:
            return held[0].upper()
        return held

    # Somebody else's name is not the candidate's, however the field is
    # labelled. A form asks for plenty of names that are not the candidate's,
    # and answering one with their own reads as an answer rather than a gap.
    if about_someone_else(label, section):
        return None

    text = " ".join(str(label or "").split())
    if not text or not is_name_field(text):
        return None
    context = "%s %s" % (identity or "", section or "")

    legal_first = profile.get("legal_first_name") or profile.get("first_name")
    legal_last = profile.get("legal_last_name") or profile.get("last_name")
    known_first = profile.get("preferred_first_name") or profile.get("first_name")
    known_last = profile.get("preferred_last_name") or profile.get("last_name")

    # The field's own id and its heading decide it when the label cannot.
    explicit_legal = bool(LEGAL.search(text)) or bool(LEGAL.search(context))
    explicit_preferred = (bool(PREFERRED.search(text))
                          or bool(PREFERRED.search(context)))
    # An id naming one of them outright beats everything else.
    if ID_LEGAL.search(identity or ""):
        explicit_legal, explicit_preferred = True, False
    elif ID_PREFERRED.search(identity or ""):
        explicit_legal, explicit_preferred = False, True

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
