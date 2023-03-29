import requests
import datetime
import logging
from dataclasses import dataclass

MODULE_NAME = __name__.split(".")[-1]


@dataclass
class ReadwiseHighlight:
    id: int
    external_id: str
    text: str
    note: str
    location: int
    end_location: int
    location_type: str
    color: str
    highlighted_at: str
    created_at: str
    updated_at: str
    url: str
    book_id: int
    tags: list[str]
    is_favorite: bool
    is_discard: bool
    readwise_url: str


@dataclass
class ReadwiseDocument:
    user_book_id: int
    # Amazon Standard Identification Number (ASIN)
    # This is not always populated.
    asin: str
    title: str
    readable_title: str
    author: str
    cover_image_url: str
    source_url: str
    # Share URL (read.readwise.io/...)
    unique_url: str
    readwise_url: str
    book_tags: list[str]
    category: str  # ENUM
    source: str
    document_note: str
    highlights: list[ReadwiseHighlight]

    def __post_init__(self):
        self.highlights = [ReadwiseHighlight(**h) for h in self.highlights]


class ReadwiseClient:
    def __init__(self, api_key: str = None):
        self._base_url = f"https://readwise.io/api/v2"
        self._parent_logger = None
        self._logger = logging.getLogger(MODULE_NAME)
        self.latest_fetch_time = None
        self.set_api_key(api_key)

    def set_parent_logger(self, parent_logger):
        self._parent_logger = parent_logger
        self._logger = self._parent_logger.getChild(MODULE_NAME)
        return self

    def set_api_key(self, api_key):
        self._api_key = api_key
        return self

    def _update_time(self):
        self.latest_fetch_time = datetime.datetime.now()

    # Taken from https://readwise.io/api_deets
    def export(self, updated_after=None):
        # TODO: Add support for backing off
        # The Readwise API returns a value to backoff for. See https://readwise.io/api_deets
        self._logger.info("Exporting Readwise data")
        self._update_time()
        full_data = []
        next_page_cursor = None
        while True:
            params = {}
            if next_page_cursor:
                params["pageCursor"] = next_page_cursor
            if updated_after:
                params["updatedAfter"] = updated_after
            self._logger.debug(
                f"Making Readwise export API request with params={params}"
            )
            response = requests.get(
                url=f"{self._base_url}/export/",
                params=params,
                headers={"Authorization": f"Token {self._api_key}"},
                verify=True,
            )
            try:
                response.raise_for_status()
                json_data = response.json()
                results = json_data["results"]
            except Exception as e:
                self._logger.debug({"response": response.text}, exc_info=e)
                self._logger.exception(e, exc_info=e)
                raise e
            full_data.extend(ReadwiseDocument(**d) for d in results)
            self._logger.debug(f"Fetched {len(results)} documents in this page")
            next_page_cursor = json_data.get("nextPageCursor")
            if not next_page_cursor:
                break
        self._logger.info("Finished exporting Readwise data")
        self._logger.debug(f"Fetched {len(full_data)} documents in total")
        num_doc_notes = sum(1 for d in full_data if d.document_note)
        self._logger.debug(f"Fetched {num_doc_notes} document notes in total")
        num_highlights = sum(len(d.highlights) for d in full_data if d.highlights)
        self._logger.debug(f"Fetched {num_highlights} highlights in total")
        return full_data

    def updates(self):
        if not self.latest_fetch_time:
            return self.export()
        self._update_time()
        return self.export(updated_after=self.latest_fetch_time.isoformat())
