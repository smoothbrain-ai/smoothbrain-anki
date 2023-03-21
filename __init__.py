import datetime
import concurrent
import anki
from anki.collection import Collection

# import the main window object (mw) from aqt
from aqt import mw, gui_hooks
# import the "show info" tool from utils.py
from aqt.utils import showInfo, qconnect
from aqt.operations import CollectionOp
# import all of the Qt GUI library
from aqt.qt import *

import os
import pathlib
import sys

ADDON_ROOT_DIR = pathlib.Path(__file__).parent.resolve()
LIBRARY_SUB_DIR = "vendor"
LIBRARY_PATH = os.path.join(ADDON_ROOT_DIR, LIBRARY_SUB_DIR)
sys.path.append(LIBRARY_PATH)
sys.path.append(ADDON_ROOT_DIR)

# We vendor the OpenAI module so need to import it after updating sys.path
import openai  # noqa: E402

from .readwise import ReadwiseClient
from .logging_utils import make_logger
from .notetype import SmoothBrainNotetype
from .config import Config

LOG_FILE = os.path.join(ADDON_ROOT_DIR, f"{__name__}.log")
logger = make_logger(__name__, filepath=LOG_FILE)

config = Config(mw.addonManager)
OPENAI_API_KEY = config["openai_api_key"]
READWISE_API_KEY = config["readwise_api_key"]
DECK_NAME = config["deck_name"]

OPENAI_DEFAULT_MODEL = "text-davinci-003"
OPENAI_MAX_TOKENS = 4096
OPENAI_MAX_OUTPUT_TOKENS = 256
openai.api_key = OPENAI_API_KEY
openai.api_base = config.get("openai_base_url", "https://oai.hconeai.com/v1")  # Helicone for stats


# We're going to add a menu item below. First we want to create a function to
# be called when the menu item is activated.
def get_ai_flashcards_for_highlight(highlight):
    # TODO: give pos/neg examples of what it gives me but what I actually want
    # TODO: Try using Curie / Davinci with fine-tuning
    # TODO: Handle list/composite highlights
    # TODO: Add retry logic, only surface error after a few tries with backoff
    # TODO: Let them be bad but let user re-gen it with a prompt. Save prompt
    prompt_template = f"""
    Make a succinct flash card for the following:
    
    {{}}
    
    Remember to:
    1. Be straight to the point.
    2. Only test ONE fact.
    3. Prefer Q&A format.
    """
    return complete(prompt_template.format(highlight.text))


def make_flashcard(doc, highlight, openai_response):
    pass

def do_sync():
    def op(col: Collection):
        notetype = SmoothBrainNotetype(col)
        want_cancel = False
        def update_progress(label, value=None, max=None):
            def cb():
                mw.progress.update(label=label, value=value, max=max)
                nonlocal want_cancel
                want_cancel = mw.progress.want_cancel()
            mw.taskman.run_on_main(cb)

        undo_entry = col.add_custom_undo_entry("Sync Readwise")
        docs = get_filtered_readwise_highlights()
        # TODO: Make the deck have a certain template
        deck_id = col.decks.add_normal_deck_with_name(DECK_NAME).id
        notes = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        future_to_note = {}
        for i, doc in enumerate(docs[:1], start=1):
            if want_cancel:
                break
            update_progress(f"Processing document {i} out of {len(docs)}...", value=i-1, max=len(docs))
            for hl in doc.highlights:
                note, added = notetype.get_or_create(doc, hl)
                notes.append(note)
                if added:
                    future = executor.submit(lambda h: get_ai_flashcards_for_highlight(h).choices[0].text.strip(), hl)
                    future_to_note[future] = note
                    # model = mw.col.models.by_name("Basic")
                    # note = mw.col.new_note(model)
                    # note["Front"] = question
                    # note["Back"] = answer
                    col.add_note(note=note, deck_id=deck_id)
                # Merge to our custom undo entry before the undo queue fills up and Anki discards our entry
                if (col.undo_status().last_step - undo_entry) % 29 == 0:
                    col.merge_undo_entries(undo_entry)
        for i, future in enumerate(concurrent.futures.as_completed(future_to_note), start=1):
            if want_cancel:
                break
            update_progress(f"Generating question {i} out of {len(future_to_note.keys())}...", value=i-1, max=len(future_to_note.keys()))
            note = future_to_note[future]
            completion = future.result()
            question, answer = completion.split("A:")
            question = question[len("Q: ") :]
            note["question"] = question
            note["answer"] = answer

        col.update_notes(notes)
        return col.merge_undo_entries(undo_entry)

    CollectionOp(parent=mw, op=op).run_in_background()

def get_filtered_readwise_highlights():
    latest_fetch_time = datetime.datetime.fromisoformat(config["latest_fetch_time"]) if config["latest_fetch_time"] else None
    readwise_client = ReadwiseClient(api_key=READWISE_API_KEY, latest_fetch_time=latest_fetch_time).set_parent_logger(logger)
    docs = readwise_client.updates()
    config["latest_fetch_time"] = datetime.datetime.isoformat(readwise_client.latest_fetch_time)
    sources_to_ignore = {
        # Things that we didn't highlight. Readwise adds
        # supplemental popular highlights from things we've read,
        # which is nice, but I think people should be intentional
        # about what they memorize. Maybe it makes sense to allow
        # these since they are often high-quality notes, and just
        # delete them when you see them (in whatever application
        # you make).
        "supplemental",
        # Things that aren't highlightable (audio/video)
        # If you take good notes (or can filter the good notes),
        # or can use the timestamp to transcribe the media, you might
        # want to add these back.
        "podcast",
        "airr",
        # Twitter highlights are kinda noisy. For me they are usually
        # the first Tweet in a bookmarked threads, and only some of that
        # is stuff I'd want to memorize.
        "twitter",
    }
    filtered_highlights = [
        d for d in docs
        if d.source not in sources_to_ignore
        # Only fetch highlights
        # TODO: Add support for x["document_note"]
        if d.highlights
    ]
    return filtered_highlights


# TODO: Use backoff and/or rate-limit
# TODO: Allow these parameters to be customized in advanced menu
def complete(prompt):
    return openai.Completion.create(engine=OPENAI_DEFAULT_MODEL,
                                    prompt=prompt,
                                    max_tokens=OPENAI_MAX_OUTPUT_TOKENS,
                                    temperature=0.5,
                                    top_p=1,
                                    frequency_penalty=0,
                                    presence_penalty=0)

def setup_menu():
    # TODO: Pass in top level menu and derive window from it
    # Create the menu button
    action = QAction("Sync Readwise", mw)
    qconnect(action.triggered, do_sync)
    # and add it to the tools menu
    action.setShortcut(QKeySequence("Ctrl+R"))
    mw.form.menuTools.addAction(action)

def setup_hooks():
    gui_hooks.sync_did_finish.append(do_sync)

#setup_hooks()

if (QAction != None and mw != None):
    setup_menu()
    #mw.form.menuTool
    #setup_menu(

"""
TODO:
- Create flashcards in deck
-- Custom card type? Just do Q&A at first, then add fields.
- Cache Readwise results
- Store last-fetch date (to reduce query to readwise/service)
- Make Flask backend in Replit in order to support fine-tuning/subscription
- Config screen
- Refactor
"""

