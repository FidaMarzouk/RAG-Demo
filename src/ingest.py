"""
Load the knowledge base: read sample_docs/, split into chunks, embed with
Ollama, write to pgvector. Idempotent: the table is cleared first.

    python -m src.ingest

Reads .txt and .md files. For PDFs, `pip install llama-index-readers-file`
and add ".pdf" to EXTENSIONS.
"""

from __future__ import annotations

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from .config import get_settings
from .store import embed_model, vector_store

EXTENSIONS = [".txt", ".md"]


def main() -> None:
    s = get_settings()
    documents = SimpleDirectoryReader(str(s.docs_dir), required_exts=EXTENSIONS).load_data()
    if not documents:
        raise SystemExit(f"No {EXTENSIONS} files in {s.docs_dir}")

    store = vector_store()
    store.clear()  # re-running ingest replaces the corpus instead of duplicating it

    splitter = SentenceSplitter(chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap)
    VectorStoreIndex.from_documents(
        documents,
        storage_context=StorageContext.from_defaults(vector_store=store),
        embed_model=embed_model(),
        transformations=[splitter],
        show_progress=True,
    )
    names = sorted({d.metadata.get("file_name", "?") for d in documents})
    print(f"Ingested {len(documents)} documents into table '{s.table_name}': {', '.join(names)}")


if __name__ == "__main__":
    main()
