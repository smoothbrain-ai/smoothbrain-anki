import datetime
import json
import concurrent
import concurrent.futures
import anki
from anki.collection import Collection
import pickle
#from anki.utils import debug

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


OPENAI_DEFAULT_MODEL = "gpt-4"


# TODO: Make this a decorator so it can reset the value after the function completes (or if it errors)
def set_openai_api_parameters(config):
    openai.api_key = config["openai_api_key"]
    openai.api_base = config.get("openai_api_base", openai.api_base)


# def do_sync():
#     @log_exceptions(logger)
#     def op(col: Collection):
#         # TODO: Get latest fetch time from deck instead of config (what if we delete the deck?)
#         # TODO: Remove duplicate or VERY similar cards even if from different highlights
#         notetype = SmoothBrainNotetype(col)
#         want_cancel = False

#         def update_progress(label, value=None, max=None):
#             def cb():
#                 mw.progress.update(label=label, value=value, max=max)
#                 nonlocal want_cancel
#                 want_cancel = mw.progress.want_cancel()

#             mw.taskman.run_on_main(cb)

#         undo_entry = col.add_custom_undo_entry("Sync Readwise")
#         docs = get_filtered_readwise_highlights()
#         docs = (
#             docs[: config["max_num_docs_to_fetch"]]
#             if "max_num_docs_to_fetch" in config
#             else docs
#         )

#         # TODO: Wait until flashcards are generated before adding them to the deck.
#         # Should probably use an SQLite database to store partial results so they don't
#         # pollute the Anki database.
#         deck_id = col.decks.add_normal_deck_with_name(config["deck_name"]).id
#         notes = []
#         executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
#         future_to_note = {}
#         try:
#             for i, doc in enumerate(docs, start=1):
#                 if want_cancel:
#                     break
#                 update_progress(
#                     f"Fetching Readwise document {i} of {len(docs)}...",
#                     value=i - 1,
#                     max=len(docs),
#                 )
#                 for hl in doc.highlights:
#                     debug(f"Debug: hl.note = {hl.note}")
#                     note, added = notetype.get_or_create(doc, hl)
#                     notes.append(note)
#                     if added:
#                         future = executor.submit(
#                             lambda h: complete(
#                                 h.text, config.get("openai_model", OPENAI_DEFAULT_MODEL), h.note
#                             )
#                             .choices[0]["message"]["content"]
#                             .strip(),
#                             hl
#                         )
#                         future_to_note[future] = note
#                         col.add_note(note=note, deck_id=deck_id)
#                     # Merge to our custom undo entry before the undo queue fills up and Anki discards our entry
#                     if (col.undo_status().last_step - undo_entry) % 29 == 0:
#                         col.merge_undo_entries(undo_entry)

#             for i, future in enumerate(
#                 concurrent.futures.as_completed(future_to_note), start=1
#             ):
#                 if want_cancel:
#                     break
#                 update_progress(
#                     f"Generating questions for highlight {i} of {len(future_to_note.keys())}...",
#                     value=i - 1,
#                     max=len(future_to_note.keys()),
#                 )
#                 completion = future.result()
#                 try:
#                     note = future_to_note[future]
#                     result = json.loads(completion)
#                     if not result:
#                         col.sched.suspend_cards([n.id for n in note.cards()])
#                         continue
#                     # TODO: Use all of the responses, and don't add a note if it doesn't have a flashcard.
#                     note["question"] = result[0]["question"]
#                     note["answer"] = result[0]["answer"]
#                 except json.decoder.JSONDecodeError as e:
#                     logger.error(
#                         f"Failed to parse completion as JSON. Completion: {completion}"
#                     )
#                     raise e
#                 except ValueError as e:
#                     logger.error(
#                         f"Failed to split completion into question and answer. Result: {result}"
#                     )
#                     raise e
#         finally:
#             col.update_notes(notes)
#         return col.merge_undo_entries(undo_entry)

#     CollectionOp(parent=mw, op=op).run_in_background()
def save_highlight(hl, filename):
    with open(filename, 'wb') as f:
        pickle.dump(hl, f)

def load_highlight(filename):
    with open(filename, 'rb') as f:
        return pickle.load(f)
        
from aqt.utils import showInfo

def do_sync():
    @log_exceptions(logger)
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
        docs = (
            docs[: config["max_num_docs_to_fetch"]]
            if "max_num_docs_to_fetch" in config
            else docs
        )

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
                    # Print hl.note content
                    #showInfo(str(hl.note))
                    note, added = notetype.get_or_create(doc, hl)
                    notes.append(note)
                    if added:
                        # Save a highlight object to a file
                        #save_highlight(hl, 'C:/Users/lisar/Downloads/highlight.pkl')
                        #note_note = note.note
                        future = executor.submit(
                            lambda h: complete(
                                h.text, config.get("openai_model", OPENAI_DEFAULT_MODEL), "make the flashcards in german, keeping the same syntax as described above"  #note["note"]#note_note# hl.note #note_note
                            )
                            .choices[0]["message"]["content"]
                            .strip(),
                            hl
                        )
                        future_to_note[future] = note
                        col.add_note(note=note, deck_id=deck_id)
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
                    #note["question"] = f"{result[0]['question']}\nNote: {hl.note}"
                    note["question"] = result[0]["question"]
                    note["answer"] = result[0]["answer"] #str(hl.note) 
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
    readwise_client = (
        ReadwiseClient(api_key=config["readwise_api_key"])
        .set_parent_logger(logger)
        .set_latest_fetch_time(latest_fetch_time)
    )
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
def complete(prompt, model, note):
    set_openai_api_parameters(config)
    # https://platform.openai.com/playground?mode=chat&model=gpt-4 is a great way to test this.
    
    system = """You are an advanced AI programmed to generate educational flashcards for active recall learning. Your role is to extract and enhance key facts from provided text and present them in a succinct, educational format. Here’s your task breakdown:

1. **Summarization & Enrichment**: Condense and enrich long texts into compact paragraphs, ensuring the essence and educational value of the content are preserved.
2. **Cloze Deletion Strategy**: When crafting cloze deletions, focus on both the key concept and its definition. Ensure that:
    - The key concept is one cloze deletion.
    - The definition or description of the concept is broken down into one or more additional cloze deletions, that can have auxiliary words in the middle, for example the same cloze deletion c2 is splited: [ {"question": "In statistics, the {{c1::range}} of a sample is calculated as the {{c2::maximum}} minus the {{c2::minimum}}, which is denoted as {{c3::x(n) – x(1)}}.", "answer": "In statistics, the range of a sample is calculated as the maximum minus the minimum, which is denoted as x(n) – x(1)."} ]
3. **Flashcard Structuring**: Compose each fact as a JSON object with "question" and "answer" fields. The "question" should contain the text with cloze deletions, while the "answer" presents the complete fact.
4. **Contextual Relevance & Brevity**: Provide sufficient context to make the flashcard meaningful. Keep the flashcards concise, focusing on the core information.
5. **Cloze Deletion Optimization**: Aim for at least two and maximum three cloze deletions per flashcard, ensuring that both the concept and its definition are adequately cloze deleted for effective reciprocal recall.
6. **Factual Accuracy & Clarity**: Ensure the flashcards are factually accurate and clearly presented.

Example:

Good example: Input: "A rate ratio is the relative increase in the expected number of events in a fixed period of time associated with an exposure." Output: [ {"question": "A {{c1::rate ratio}} is the {{c2::relative increase in the expected number of events}} in a {{c2::fixed period of time}} associated with {{c3::an exposure}}.", "answer": "A rate ratio is the relative increase in the expected number of events in a fixed period of time associated with an exposure."} ]

Key Guidelines:

- Ensure the context in the question sufficiently supports the answer.
- Facts used should be verifiable and accurate.
- Cloze delete both the concept and its definition for reciprocal learning.
- Expand on the information if necessary, but maintain conciseness in flashcards.

Note specifically for this Highlight (if its empty, ignore):\n{note_placeholder}
""".format(note_placeholder=note)#.replace("{note_placeholder}", str(note))

    #system = system_template
    #if note:
        #prompt += f"\n\nNote: {note}"
        
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

