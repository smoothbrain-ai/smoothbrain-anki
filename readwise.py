import requests
from dataclasses import dataclass


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
    def __init__(self, api_key: str=None):
        self._base_url = f"https://readwise.io/api/v2"
        self.set_api_key(api_key)

    def set_api_key(self, api_key):
        self._api_key = api_key
        return self
    
    # Taken from https://readwise.io/api_deets
    def export(self, updated_after=None):
        # If you want to get new highlights updated since your last fetch of allData, do this.
        # #last_fetch_was_at = datetime.datetime.now() - datetime.timedelta(days=1)  # use your own stored date
        # new_data = fetch_from_export_api(last_fetch_was_at.isoformat())
        full_data = []
        next_page_cursor = None
        while True:
            params = {}
            if next_page_cursor: params["pageCursor"] = next_page_cursor
            if updated_after: params["updatedAfter"] = updated_after
            response = requests.get(
                url=f"{self._base_url}/export/",
                params=params,
                headers={"Authorization": f"Token {self._api_key}"},
                verify=True)
            json_data = response.json()
            collection = json_data["results"]
            full_data.extend(ReadwiseDocument(**d) for d in collection)
            next_page_cursor = json_data.get("nextPageCursor")
            if not next_page_cursor:
                break
        return full_data
