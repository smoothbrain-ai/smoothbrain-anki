from anki.collection import Collection
from anki.models import NotetypeDict
from anki.notes import Note
from anki.stdmodels import get_stock_notetypes
from markdown import markdown

from .readwise import ReadwiseDocument, ReadwiseHighlight


class SmoothBrainBasicTemplate:
    name = "Card 1"
    question = """{{question}}"""
    answer = """{{FrontSide}}

<hr id=answer>

{{answer}}"""


class SmoothBrainNotetype:
    name = "SmoothBrain"
    templates = [SmoothBrainBasicTemplate]
    fields = [
        "id",
        "question",
        "answer",
        # Highlight fields
        "text",
        "note",
        "url",
        "readwise_url",
        "highlighted_at",
        "created_at",
        "updated_at",
        # Document fields
        "book_id",
        "title",
        "author",
        "source",
        "source_url",
        "category",
        "asin",
    ]

    def __init__(self, col: Collection) -> None:
        self.col = col
        basic_notetype = get_stock_notetypes(col)[0][1](col)
        self.css = basic_notetype["css"]
        self.notetype = self._ensure_exists()

    def _ensure_exists(self) -> NotetypeDict:
        notetype = self.col.models.by_name(self.name)
        if not notetype:
            notetype = self.col.models.new(self.name)
            for readwise_template in self.templates:
                template = self.col.models.new_template(readwise_template.name)
                template["qfmt"] = readwise_template.question
                template["afmt"] = readwise_template.answer
                self.col.models.add_template(notetype, template)
            for field_name in self.fields:
                field = self.col.models.new_field(field_name)
                self.col.models.add_field(notetype, field)
            notetype["css"] = self.css
            self.col.models.set_sort_index(notetype, self.fields.index("question"))
            self.col.models.add_dict(notetype)
            # We need to refetch the notetype after adding it
            notetype = self.col.models.by_name(self.name)
        return notetype

    def _format_field(self, contents) -> str:
        text = ""
        if contents:
            text = str(contents)
        return text

    def _format_url(self, contents) -> str:
        url = self._format_field(contents)
        if url:
            url = f'<a href="{url}">{url}</a>'
        return url

    def new_note(
        self, doc: ReadwiseDocument, highlight: ReadwiseHighlight, completion: str
    ) -> Note:
        note = self.col.new_note(self.notetype)
        question, answer = completion.split("A:")
        question = question[len("Q: ") :]
        note = self.col.new_note(self.notetype)
        note["id"] = self._format_field(highlight.id)
        note["question"] = self._format_field(question)
        note["answer"] = self._format_field(answer)
        note["text"] = markdown(self._format_field(highlight.text))
        note["note"] = self._format_field(highlight.note)
        note["url"] = self._format_url(highlight.url)
        note["readwise_url"] = self._format_url(highlight.readwise_url)
        note["highlighted_at"] = self._format_field(highlight.highlighted_at)
        note["created_at"] = self._format_field(highlight.created_at)
        note["updated_at"] = self._format_field(highlight.updated_at)
        note["book_id"] = self._format_field(doc.user_book_id)
        note["title"] = self._format_field(doc.readable_title)
        note["author"] = self._format_field(doc.author)
        note["source"] = self._format_field(doc.source)
        note["source_url"] = self._format_url(doc.source_url)
        note["category"] = self._format_field(doc.category)
        note["asin"] = self._format_field(doc.asin)
        note.tags = [tag["name"] for tag in doc.book_tags + highlight.tags]

        return note
