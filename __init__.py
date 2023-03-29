import datetime
import json
import concurrent
import concurrent.futures
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
from .logging_utils import make_logger, log_exceptions
from .notetype import SmoothBrainNotetype
from .config import Config

# TODO: Let users define the log level in the config
LOG_FILE = os.path.join(ADDON_ROOT_DIR, f"{__name__}.log")
logger = make_logger(__name__, filepath=LOG_FILE)

config = Config(mw.addonManager)

OPENAI_DEFAULT_MODEL = "text-davinci-003"
OPENAI_MAX_TOKENS = 4096
OPENAI_MAX_OUTPUT_TOKENS = 256


def max_num_docs_to_fetch():
    return config.get("debug", dict()).get("max_num_docs_to_fetch", None)


def max_num_highlights_to_fetch():
    return config.get("debug", dict()).get("max_num_highlights_to_fetch", None)


def set_openai_api_parameters(config):
    openai.api_key = config["openai_api_key"]
    openai.api_base = config.get("openai_api_base", openai.api_base)


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

    Return the answer as a JSON object with the keys "question" and "answer".
    
    Remember to:
    1. Be straight to the point.
    2. Only test ONE fact.
    3. Prefer Q&A format.
    """
    return complete(prompt_template.format(highlight.text))


def do_sync():
    @log_exceptions(logger)
    def op(col: Collection):
        # TODO: Don't add partial questions
        # TODO: Get latest fetch time from deck instead of config (what if we delete the deck?)
        # TODO: Remove duplicate or VERY similar cards even if from different highlights
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
        docs = docs[: max_num_docs_to_fetch()] if max_num_docs_to_fetch() else docs

        deck_id = col.decks.add_normal_deck_with_name(config["deck_name"]).id
        notes = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        future_to_note = {}
        try:
            for i, doc in enumerate(docs, start=1):
                if want_cancel:
                    break
                update_progress(
                    f"Fetching Readwise document {i} out of {len(docs)}...",
                    value=i - 1,
                    max=len(docs),
                )
                for hl in doc.highlights:
                    note, added = notetype.get_or_create(doc, hl)
                    notes.append(note)
                    if added:
                        future = executor.submit(
                            lambda h: get_ai_flashcards_for_highlight(h)
                            .choices[0]["message"]["content"]
                            .strip(),
                            hl,
                        )
                        future_to_note[future] = note
                        col.add_note(note=note, deck_id=deck_id)
                    # Merge to our custom undo entry before the undo queue fills up and Anki discards our entry
                    if (col.undo_status().last_step - undo_entry) % 29 == 0:
                        col.merge_undo_entries(undo_entry)

            for i, future in enumerate(
                concurrent.futures.as_completed(future_to_note), start=1
            ):
                if want_cancel:
                    break
                update_progress(
                    f"Generating question {i} out of {len(future_to_note.keys())}...",
                    value=i - 1,
                    max=len(future_to_note.keys()),
                )
                note = future_to_note[future]
                completion = future.result()
                result = json.loads(completion)
                try:
                    note["question"] = result["question"]
                    note["answer"] = result["answer"]
                except ValueError as e:
                    logger.error(
                        f"Failed to split completion into question and answer. Result: {result}"
                    )
                    raise e
        finally:
            col.update_notes(notes)
        return col.merge_undo_entries(undo_entry)

    CollectionOp(parent=mw, op=op).run_in_background()


@log_exceptions(logger)
def get_filtered_readwise_highlights():
    latest_fetch_time = (
        datetime.datetime.fromisoformat(config["latest_fetch_time"])
        if config["latest_fetch_time"]
        else None
    )
    readwise_client = ReadwiseClient(
        api_key=config["readwise_api_key"], latest_fetch_time=latest_fetch_time
    ).set_parent_logger(logger)
    docs = readwise_client.updates()
    config["latest_fetch_time"] = datetime.datetime.isoformat(
        readwise_client.latest_fetch_time
    )
    sources_to_ignore = {
        # TODO: Allow these to be configured
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
        d
        for d in docs
        if d.source not in sources_to_ignore
        # Only fetch highlights
        if d.highlights
        # TODO: Filter tags
    ]
    return filtered_highlights


def chat_complete(prompt):
    completion = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        headers={
            "Helicone-Cache-Enabled": "true",
        },
    )
    return completion


def standard_complete(prompt):
    return openai.Completion.create(
        engine=OPENAI_DEFAULT_MODEL,
        prompt=prompt,
        max_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        temperature=0.5,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        # If we use Helicone we can speed up repeat runs during development.
        # Will be ignored if using OpenAI directly.
        headers={
            "Helicone-Cache-Enabled": "true",
        },
    )


# TODO: Use backoff and/or rate-limit
# TODO: Allow these parameters to be customized in advanced menu
@log_exceptions(logger)
def complete(prompt):
    set_openai_api_parameters(config)
    return chat_complete(prompt)


@log_exceptions(logger)
def setup_menu():
    # TODO: Pass in top level menu and derive window from it
    # Create the menu button
    action = QAction("Sync Readwise", mw)
    qconnect(action.triggered, do_sync)
    # and add it to the tools menu
    action.setShortcut(QKeySequence("Ctrl+R"))
    mw.form.menuTools.addAction(action)


# TODO: Consider automating syncing
# @log_exceptions(logger)
# def setup_hooks():
#    gui_hooks.sync_did_finish.append(do_sync)
# setup_hooks()

if QAction != None and mw != None:
    setup_menu()
