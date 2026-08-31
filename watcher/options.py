"""What an option on a list actually asserts.

Matching an answer to a dropdown option by tidying up the text and comparing
it has failed repeatedly, because the text is not a name -- it is a small
statement. "Asian (Not Hispanic or Latino) (United States of America)" asserts
one thing, Asian, and then qualifies it twice: once by saying what it is not,
and once by naming the country the classification belongs to.

Read that way the reasoning is straightforward and does not depend on the
employer's phrasing:

  * An option is about its head -- the part before its qualifiers. The rest
    narrows it, and a candidate's fact appearing only in a qualifier says
    nothing about what the option is for. A stored country matching the
    "(United States of America)" on an option about Hispanic origin is not a
    reason to call someone Hispanic.

  * A qualifier that negates does not assert. "Not Hispanic or Latino" is
    evidence the option is *not* the Hispanic one, so it must never match a
    Hispanic fact -- the opposite of what a substring search would conclude.

  * A fact stated plainly answers an option that names it, however much else
    the option says. "Asian" answers "Asian (Not Hispanic or Latino)" because
    Asian is what that option is about.
"""

import re

# Words that join categories rather than narrowing one.
_JOINING = frozenset(("or", "and", "of", "the", "a", "an", "either", "both"))

_NEGATION = re.compile(r"\b(?:not|non|excluding|other\s+than|except)\b", re.I)
_SPLIT = re.compile(r"[\s/,;|]+")
# Words that carry no meaning of their own. A country's name is not among
# them: "United States" reduced to nothing here, so a dialling-code list full
# of countries could not be answered with the candidate's own. The country
# qualifier on an EEO option is stripped by reading the head instead.
_NOISE = frozenset((
    "the", "of", "at", "in", "and", "a", "an", "for", "is", "are", "my",
    "your", "i", "am", "have", "has",
))


def head_of(option):
    """What the option is about, before anything qualifying it."""
    text = " ".join(str(option or "").split())
    head = re.split(r"\s*[(\[]", text, 1)[0]
    return head.strip().rstrip(".,;:").strip()


def qualifiers_of(option):
    """The bracketed notes after the head, in order."""
    return [q.strip() for q in
            re.findall(r"[(\[]([^()\[\]]*)[)\]]", str(option or ""))]


def _terms(text):
    """Meaningful words, with the filler that appears on every list removed."""
    words = [w.strip(".,;:'\"").lower() for w in _SPLIT.split(str(text or ""))]
    return [w for w in words if w and w not in _NOISE]


def asserts(option, fact):
    """Does this option assert that fact? Returns a strength, 0 if not.

    2 -- the option is exactly the fact
    1 -- the fact is what the option is about, among other words
    0 -- not asserted, or asserted only inside a qualifier, or negated
    """
    fact_terms = _terms(fact)
    if not fact_terms:
        return 0

    head = head_of(option)
    head_terms = _terms(head)
    if not head_terms:
        return 0

    if head_terms == fact_terms:
        return 2

    # The fact's words, in order, somewhere in the head: "Asian" within
    # "Asian or Pacific Islander".
    joined = " ".join(head_terms)
    phrase = " ".join(fact_terms)
    if re.search(r"(?:^| )%s(?:$| )" % re.escape(phrase), joined):
        before = joined.split(phrase)[0].split()
        # Unless the head itself denies it: "Not Hispanic or Latino".
        if before and _NEGATION.search(before[-1]):
            return 0
        # A word in front narrows the term: "East Asian" is a kind of Asian,
        # not Asian itself, and someone who said Asian has not said which
        # kind. Choosing one for them is inventing a fact about who they are.
        # A term extended after itself is broader and still covers them --
        # "Asian or Pacific Islander" includes an Asian candidate.
        if before and before[-1] not in _JOINING:
            return 0
        return 1
    return 0


def denies(option, fact):
    """Does the option say it is *not* that fact?

    "Asian (Not Hispanic or Latino)" denies Hispanic origin, which is the
    opposite of what looking for the words alone would conclude.
    """
    fact_terms = _terms(fact)
    if not fact_terms:
        return False
    phrase = " ".join(fact_terms)
    for qualifier in qualifiers_of(option) + [head_of(option)]:
        terms = " ".join(_terms(qualifier))
        if phrase not in terms:
            continue
        before = terms.split(phrase)[0]
        if _NEGATION.search(before):
            return True
    return False


def best(options, facts):
    """The option asserting one of these facts: (option, fact) or (None, None).

    Facts are tried in the order given, and the strongest assertion wins. Where
    two options assert equally the list is genuinely ambiguous and neither is
    taken.
    """
    for fact in facts:
        if not fact:
            continue
        scored = []
        for option in options or []:
            if denies(option, fact):
                continue
            strength = asserts(option, fact)
            if strength:
                scored.append((strength, option))
        if not scored:
            continue
        top = max(s for s, _ in scored)
        winners = [o for s, o in scored if s == top]
        if len(winners) == 1:
            return winners[0], fact
    return None, None
