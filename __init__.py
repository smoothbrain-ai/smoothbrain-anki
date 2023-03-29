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

OPENAI_DEFAULT_MODEL = "gpt-3.5-turbo"


# TODO: Make this a decorator so it can reset the value after the function completes (or if it errors)
def set_openai_api_parameters(config):
    openai.api_key = config["openai_api_key"]
    openai.api_base = config.get("openai_api_base", openai.api_base)


def do_sync():
    @log_exceptions(logger)
    def op(col: Collection):
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
        docs = (
            docs[: config["max_num_docs_to_fetch"]]
            if "max_num_docs_to_fetch" in config
            else docs
        )

        # TODO: Wait until flashcards are generated before adding them to the deck.
        # Should probably use an SQLite database to store partial results so they don't
        # pollute the Anki database.
        deck_id = col.decks.add_normal_deck_with_name(config["deck_name"]).id
        notes = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        future_to_note = {}
        try:
            for i, doc in enumerate(docs, start=1):
                if want_cancel:
                    break
                update_progress(
                    f"Fetching Readwise document {i} of {len(docs)}...",
                    value=i - 1,
                    max=len(docs),
                )
                for hl in doc.highlights:
                    note, added = notetype.get_or_create(doc, hl)
                    notes.append(note)
                    if added:
                        future = executor.submit(
                            lambda h: complete(
                                h.text, config.get("openai_model", OPENAI_DEFAULT_MODEL)
                            )
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
                    f"Generating questions for highlight {i} of {len(future_to_note.keys())}...",
                    value=i - 1,
                    max=len(future_to_note.keys()),
                )
                completion = future.result()
                try:
                    note = future_to_note[future]
                    result = json.loads(completion)
                    if not result:
                        col.sched.suspend_cards([n.id for n in note.cards()])
                        continue
                    # TODO: Use all of the responses, and don't add a card if it doesn't have a flashcard.
                    note["question"] = result[0]["question"]
                    note["answer"] = result[0]["answer"]
                except json.decoder.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse completion as JSON. Completion: {completion}"
                    )
                    raise e
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


# TODO: Use backoff and/or rate-limit.
# TODO: Ask GPT to add a reason if there are no questions, for debugging.
# TODO: Generate questions for entire doc, and fetch the entire doc if possible to improve the context
@log_exceptions(logger)
def complete(prompt, model):
    set_openai_api_parameters(config)
    # https://platform.openai.com/playground?mode=chat&model=gpt-4 is a great way to test this.
    system = """
    You are the worlds best flashcard making machine, ushering in a new age of education.

You extract the most interesting fact triples from the input, then return a JSON list of objects which have a "question" field and an "answer" field. If input is missing information or has no interesting facts worth remembering, return an empty list.

Good examples:
Input: Guido Van Rossum invented Python in 1989.
Output: [{"question": "Who invented Python?", "answer": "Guido Van Rossum"}, {"question": "Which year was Python invented?", "1989"}]

Examples of no good facts:
The following example returns an empty result because even though the mass of Jupiter is interesting, we don't know what "The seminar":
Input: The seminar covered the mass of Jupiter
Output: []

The following is an incorrect fact, so no question is returned:
Input: The mass of Jupiter is 1kg
Output: []

The following is an example of an opinion:
Input: Python is the best programming language.
Output: []

Here is an example of an input with no useful facts:
Input: Our models are used for both research purposes and developer use cases in production. Researchers often learn about our models from papers that we have published, but there is often not a perfect match between what is available in the OpenAI API and what is published in a paper.
Output: []

Here are some examples of bad outputs, don't do these:
The following is bad because the question doesnt give context of what sort of answer it is expecting, and it could be multiple answers:
Input: `text-davinci-002` is an InstructGPT model based on `code-davinci-002`
Output: [{"question": "What is `text-davinci-002`?", "answer": "An InstructGPT model"}]
"""
    completion = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        # TODO: Allow these parameters to be customized in config
        temperature=0,
        n=1,
        headers={
            "Helicone-Cache-Enabled": "true",
        },
    )
    return completion


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
