"""Keeping what the candidate types, and not keeping what Gary types.

Gary leaves a field alone when nothing settles it, and the candidate fills it
in. That answer is worth keeping -- employers ask the same thing in different
words, and a question answered by hand once should not need answering again.

The danger is the opposite: learning from its own writing, which would have
Gary spend every application confirming its own mistakes.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply
from watcher import learning
from playwright.sync_api import sync_playwright

failures = []

# --- what is worth keeping ------------------------------------------------ #
for question, value, keep in (
        ("Which term are you seeking an internship for?", "Summer 2027", True),
        ("What is your t-shirt size?", "Medium", True),
        # A placeholder is not an answer.
        ("Which term are you seeking?", "Select One", False),
        ("Date", "MM/DD/YYYY", False),
        # Credentials are never kept, whatever the field is called.
        ("Password", "hunter2", False),
        ("What is your social security number?", "000-00-0000", False),
        ("Date of birth", "01/01/2000", False),
        # Prose is not a reusable answer.
        ("Why do you want to work here?", "x" * 200, False)):
    got = learning.worth_keeping(question, value)
    if got != keep:
        failures.append("%r = %r: worth_keeping said %s" % (question[:34],
                                                            value[:20], got))

# --- writing to the profile ----------------------------------------------- #
handle, path = tempfile.mkstemp(suffix=".json")
os.close(handle)
with open(path, "w") as f:
    json.dump({"first_name": "RG"}, f)

profile = {"first_name": "RG"}
if not learning.remember(profile, path, "What is your t-shirt size?", "Medium"):
    failures.append("a new answer was not recorded")
with open(path) as f:
    on_disk = json.load(f)
if on_disk.get("custom_answers", {}).get("what is your t-shirt size") != "Medium":
    failures.append("the answer did not reach the profile on disk: %r"
                    % on_disk.get("custom_answers"))
if on_disk.get("first_name") != "RG":
    failures.append("writing the answer lost the rest of the profile")

# An answer already known is left alone; a correction replaces it.
if learning.remember(profile, path, "What is your t-shirt size?", "Large"):
    failures.append("an existing answer was overwritten without a correction")
if not learning.remember(profile, path, "What is your t-shirt size?", "Large",
                         corrected=True):
    failures.append("a correction did not replace what Gary believed")
os.remove(path)

# --- learning from a live form -------------------------------------------- #
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)
    page = context.new_page()
    page.set_content('''
      <div data-automation-id="formField-term">
        <label for="a">Which term are you seeking an internship for?</label>
        <input id="a" type="text">
      </div>
      <div data-automation-id="formField-name">
        <label for="b">First Name</label>
        <input id="b" type="text">
      </div>
    ''')
    apply._WROTE.clear()
    grown = {}

    # Gary left the first alone and filled the second itself.
    apply.note_written(apply.mark_of(page, page.query_selector("#a")),
                       "Which term are you seeking an internship for?", "")
    apply.note_written(apply.mark_of(page, page.query_selector("#b")),
                       "First Name", "RG")
    page.fill("#b", "RG")

    # Nothing typed by the candidate yet: nothing to learn.
    if apply.learn_from_candidate(page, grown):
        failures.append("learned something before the candidate typed anything")

    # The candidate answers the question Gary left alone.
    page.fill("#a", "Summer 2027")
    apply.learn_from_candidate(page, grown)          # noticed, still settling
    learned = apply.learn_from_candidate(page, grown)  # settled, kept
    if not learned:
        failures.append("did not learn the answer the candidate typed")
    kept = grown.get("custom_answers", {})
    if kept.get("which term are you seeking an internship for") != "Summer 2027":
        failures.append("kept %r" % kept)
    if any("first name" in k for k in kept):
        failures.append("learned from its own writing: %r" % kept)

    # A field inside a repeated entry must not be learned globally. Its
    # question does not say which entry it belongs to, so learning "Field of
    # Study" from the bachelor's would answer the master's with it too -- which
    # is what happened on the first real application this ran on.
    page.set_content("""
      <div data-automation-id="education-2">
        <div data-automation-id="formField-school">
          <label for="s">School or University</label><input id="s">
        </div>
        <div data-automation-id="formField-degree">
          <label for="d">Degree</label><input id="d">
        </div>
        <div data-automation-id="formField-fieldOfStudy">
          <label for="f">Field of Study</label><input id="f">
        </div>
      </div>
      <div data-automation-id="formField-veteran">
        <label for="v">Veteran Status</label><input id="v">
      </div>
    """)
    apply._WROTE.clear()
    entries = {}
    for box, question in (("#f", "Field of Study"), ("#v", "Veteran Status")):
        apply.note_written(apply.mark_of(page, page.query_selector(box)),
                           question, "")
    page.fill("#f", "Arts and Entertainment Technologies")
    page.fill("#v", "I am not a veteran")
    apply.learn_from_candidate(page, entries)
    apply.learn_from_candidate(page, entries)
    kept = entries.get("custom_answers", {})
    if "field of study" in kept:
        failures.append("learned an entry's field globally: %r" % kept)
    if kept.get("veteran status") != "I am not a veteran":
        failures.append("did not learn a question outside any entry: %r" % kept)

    # A value is only an answer once it has stopped changing. Reading a field
    # the moment it changes catches the first keystroke: on a real
    # application Gary recorded "N" as the answer to a question the candidate
    # was part way through answering.
    page.set_content('<label for="t">List your family member\'s name</label>'
                     '<input id="t">')
    apply._WROTE.clear()
    typing = {}
    mark = apply.mark_of(page, page.query_selector("#t"))
    apply.note_written(mark, "List your family member's name", "")

    page.fill("#t", "J")
    if apply.learn_from_candidate(page, typing):
        failures.append("learned a value while it was still being typed")
    page.fill("#t", "Jane Doe")
    if apply.learn_from_candidate(page, typing):
        failures.append("learned a value that had only just changed")
    learned = apply.learn_from_candidate(page, typing)
    if not learned:
        failures.append("never learned the value once it had settled")
    if typing.get("custom_answers", {}).get(
            "list your family member's name") != "Jane Doe":
        failures.append("settled on %r" % typing.get("custom_answers"))

    # "N/A" is a way of declining a question, not an answer worth carrying to
    # another employer.
    if learning.worth_keeping("List your family member's name", "N/A"):
        failures.append("would carry 'N/A' to another employer as an answer")

    browser.close()

total = 8 + 5 + 4 + 2 + 5
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
