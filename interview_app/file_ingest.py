"""Safe text extraction from uploaded job-description files.

Defences, in order:
1. Size limit before any parsing.
2. Extension allow-list (.txt, .md, .pdf, .docx) AND content sniffing: the bytes must match the
   claimed type, so a renamed executable or a corrupted file is rejected.
3. Format-specific limits: PDF page count and encryption; DOCX zip-entry count, uncompressed
   size (zip-bomb guard), and DTD/entity declarations (XML entity-expansion guard).
4. The extracted text then goes through the same sanitisation, length limit, and injection
   assessment as pasted text.
"""

import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from interview_app.security_guard import GuardError

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_DOCX_ENTRIES = 300
MAX_DOCX_UNCOMPRESSED = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class ExtractedText:
    text: str
    kind: str
    detail: str


def _extension(filename: str) -> str:
    name = (filename or "").lower().strip()
    return name[name.rfind("."):] if "." in name else ""


def _decode_text(data: bytes) -> str:
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise GuardError("This text file contains binary data. Please upload a plain-text document.")
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise GuardError("This text file is not valid UTF-8 or UTF-16. Please re-save it as UTF-8.")
    printable = sum(ch.isprintable() or ch in "\n\r\t" for ch in text)
    if text and printable / len(text) < 0.95:
        raise GuardError("This file does not look like readable text.")
    return text


def _extract_pdf(data: bytes) -> tuple[str, str]:
    if not data.startswith(b"%PDF-"):
        raise GuardError("This file has a .pdf extension but is not a PDF.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise GuardError("Password-protected PDFs are not supported.")
        pages = len(reader.pages)
        if pages > MAX_PDF_PAGES:
            raise GuardError(f"This PDF has {pages} pages; the limit is {MAX_PDF_PAGES}.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except GuardError:
        raise
    except Exception as error:  # pypdf raises many types for malformed files
        raise GuardError("This PDF could not be read. It may be corrupted.") from error
    return text, f"{pages} page{'s' if pages != 1 else ''}"


def _extract_docx(data: bytes) -> tuple[str, str]:
    if not data.startswith(b"PK\x03\x04"):
        raise GuardError("This file has a .docx extension but is not a Word document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise GuardError("This Word document has an unusual structure and was rejected.")
            if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED:
                raise GuardError("This Word document expands to an unsafe size and was rejected.")
            try:
                xml = archive.read("word/document.xml")
            except KeyError:
                raise GuardError("This file is not a valid Word document (missing document body).") from None
    except GuardError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise GuardError("This Word document could not be read. It may be corrupted.") from error
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise GuardError("This Word document contains XML declarations that are not allowed.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise GuardError("This Word document could not be read. It may be corrupted.") from error
    paragraphs = []
    for paragraph in root.iter(f"{_WORD_NS}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NS}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs), f"{len(paragraphs)} paragraphs"


def extract_text(filename: str, data: bytes) -> ExtractedText:
    """Return the readable text of an uploaded file, or raise GuardError with a clear reason."""
    if not data:
        raise GuardError("The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise GuardError(f"The file is {len(data) / 1024 / 1024:.1f} MB; the limit is {MAX_FILE_BYTES // 1024 // 1024} MB.")
    extension = _extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise GuardError(f"Unsupported file type '{extension or 'none'}'. Upload a .txt, .md, .pdf, or .docx file.")
    if extension == ".pdf":
        text, detail = _extract_pdf(data)
    elif extension == ".docx":
        text, detail = _extract_docx(data)
    else:
        text, detail = _decode_text(data), f"{len(data):,} bytes"
    if not text.strip():
        raise GuardError("No readable text was found in this file (scanned PDFs without text are not supported).")
    return ExtractedText(text=text, kind=extension.lstrip("."), detail=detail)
