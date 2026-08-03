"""Local DOCX extraction and deterministic Raipur v2 knowledge chunking."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

RAIPUR_LOCATION_NAME = "Entartica SeaWorld Raipur"
CHUNKING_VERSION = "raipur_v2"
RAIPUR_DOCUMENTS = (("location_information/raipur_location_information.docx","location_information"),("services/raipur_services.docx","services"),("booking_policies/raipur_booking_policy.docx","booking_policy"),("safety_guidelines/raipur_safety_guidelines.docx","safety_guidelines"),("faq/raipur_faq.docx","faq"))
_REJECTED_STATUS=("draft","pending approval","unapproved","information required")

@dataclass(frozen=True)
class KnowledgeSection:
    heading: str
    subsection_heading: str | None
    text: str

@dataclass(frozen=True)
class KnowledgeChunk:
    text: str
    section_heading: str
    subsection_heading: str | None
    index: int
    def embedding_input(self, category: str) -> str:
        if category == "faq":
            question, _, answer = self.text.partition("\n")
            return f"Location: Raipur\nCategory: faq\nIntent topic: {faq_topic(question)}\nQuestion: {question}\nAnswer: {answer}"
        return f"Location: Raipur\nCategory: {category}\nSection: {self.section_heading}\nContent: {self.text}"

@dataclass(frozen=True)
class ExtractedKnowledgeDocument:
    filename:str; category:str; text:str; source_hash:str; sections:tuple[KnowledgeSection,...]
    @property
    def metadata(self)->dict[str,str]:
        version="raipur_faq_v3" if self.category=="faq" else CHUNKING_VERSION
        return {"location_code":"raipur","location_name":RAIPUR_LOCATION_NAME,"approval_status":"approved","source_filename":self.filename,"document_category":self.category,"chunking_version":version,"embedding_context_version":version}

def required_raipur_document_paths(root:Path)->tuple[tuple[Path,str],...]: return tuple((root/r,c) for r,c in RAIPUR_DOCUMENTS)
def sanitize_filename(path:Path)->str: return re.sub(r"[^A-Za-z0-9._-]","_",path.name)
def chunk_hash(text:str)->str: return sha256(text.encode()).hexdigest()

def extract_approved_docx(path:Path,category:str)->ExtractedKnowledgeDocument:
    if not path.is_file(): raise ValueError("Required knowledge document is missing.")
    try:
        with ZipFile(path) as d: root=ElementTree.fromstring(d.read("word/document.xml"))
    except (BadZipFile,KeyError,ElementTree.ParseError) as e: raise ValueError("Knowledge document cannot be read as DOCX.") from e
    entries=_entries(root)
    raw=[text for _,text in entries]
    if _has_rejected_document_status(raw): raise ValueError("Knowledge document has a rejected approval status.")
    sections=_sections([entry for entry in entries if not _boilerplate(entry[1])],category)
    text="\n".join(section.text for section in sections).strip()
    if not text: raise ValueError("Knowledge document contains no extractable text.")
    return ExtractedKnowledgeDocument(sanitize_filename(path),category,text,sha256(text.encode()).hexdigest(),tuple(sections))

def section_chunks(document:ExtractedKnowledgeDocument,target:int=650,overlap:int=80)->list[KnowledgeChunk]:
    chunks=[]
    for section in document.sections:
        units=_faq_units(section.text) if document.category=="faq" else [section.text]
        for unit in units:
            for piece in _split(unit,target,overlap):
                clean=(section.heading+"\n"+piece).strip() if section.heading not in piece else piece
                chunks.append(KnowledgeChunk(clean,section.heading,section.subsection_heading,len(chunks)))
    return chunks

def chunk_text(text:str, *, maximum_characters:int=650)->list[str]:
    """Compatibility helper for deterministic plain-text chunk tests."""
    return _split(text, maximum_characters, 80)

def _entries(root:ElementTree.Element)->list[tuple[str,str]]:
    result=[]
    for p in root.iter():
        if not p.tag.endswith("}p"): continue
        text="".join(n.text or "" for n in p.iter() if n.tag.endswith("}t")).strip()
        if not text: continue
        style=""
        for n in p.iter():
            if n.tag.endswith("}pStyle"): style=n.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val","")
        result.append((style,text))
    for tr in root.iter():
        if tr.tag.endswith("}tr"):
            cells=[]
            for tc in tr.iter():
                if tc.tag.endswith("}tc"):
                    value=" ".join("".join(n.text or "" for n in p.iter() if n.tag.endswith("}t")).strip() for p in tc.iter() if p.tag.endswith("}p")).strip()
                    if value: cells.append(value)
            if cells: result.append(("table"," | ".join(cells)))
    return result

def _sections(entries:list[tuple[str,str]],category:str)->list[KnowledgeSection]:
    sections=[]; h1="General"; h2=None; body=[]
    def flush():
        if body: sections.append(KnowledgeSection(h1,h2,"\n".join(body)))
    for style,text in entries:
        if style.lower().startswith("heading"):
            flush(); body=[]
            if style.lower().endswith("1"): h1,h2=text,None
            else: h2=text
        else: body.append(text)
    flush()
    return sections

def _split(text:str,target:int,overlap:int)->list[str]:
    if len(text)<=target:return [text]
    words=text.split(); out=[]; current=[]
    for word in words:
        if current and len(" ".join(current+[word]))>target:
            out.append(" ".join(current)); tail=" ".join(current)[-overlap:].split(); current=tail
        current.append(word)
    if current: out.append(" ".join(current))
    return out

def _faq_units(text:str)->list[str]:
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    units=[]; i=0
    current=[]
    for line in lines:
        is_question=bool(re.match(r"^(\d+[.)]\s*)?(question\s*[:\-]|q\s*[:\-])",line,re.I) or line.endswith("?"))
        if is_question and current:
            units.append("\n".join(current)); current=[line]
        else: current.append(line)
    if current: units.append("\n".join(current))
    return units

def faq_topic(question:str)->str:
    value=question.casefold()
    for topic, words in (("location",("where","location","timing","hours","address")),("services",("activity","service","ride","boating","staycation","daycation")),("booking",("booking","enquiry","confirm","price","payment","refund","cancel")),("safety",("safety","medical","pregnancy","alcohol","life jacket")),("weather",("weather",)),("children",("child","children","age"))):
        if any(word in value for word in words): return topic
    return "general"


def faq_question(chunk: KnowledgeChunk) -> str:
    """Return the FAQ question, excluding the section heading added to a chunk."""

    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    if lines and lines[0] == chunk.section_heading and not lines[0].endswith("?"):
        lines = lines[1:]
    for line in lines:
        if line.endswith("?"):
            return line
    return ""

def _boilerplate(text:str)->bool:
    value=re.sub(r"\s+"," ",text.casefold()).strip()
    return bool(re.fullmatch(r"page \d+( of \d+)?",value) or value in {"table of contents","raipur","entartica seaworld raipur"} or re.match(r"^(document (title|version|status)|approval date|approved by|prepared by|location:)\s*[:\-]",value))
def _has_rejected_document_status(paragraphs:Iterable[str])->bool:
    for p in paragraphs:
        value=re.sub(r"\s+"," ",p.lower()).strip(" :-")
        if value in _REJECTED_STATUS or (value.startswith(("document status:","approval status:","status:")) and any(x in value for x in _REJECTED_STATUS)): return True
    return False
