-- LlamaIndex's PGVectorStore creates its own table (data_<VECTOR_TABLE>) and an
-- HNSW index on first use; the database only needs the pgvector extension.
CREATE EXTENSION IF NOT EXISTS vector;
