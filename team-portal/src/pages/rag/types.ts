// RAG corpus wire types — mirror of api/rag.py.
// Engineer-side surface: search the corpus, index/delete documents, see stats.

export interface RagStats {
  index_size: number;
  doc_count: number;
  last_updated: string | null;
  embedding_model: string;
  rejections_total: number;
  rag_enabled: boolean;
}

export interface SearchResultItem {
  id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
  bm25_score: number;
  semantic_score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  total: number;
}

export interface IndexDocumentResponse {
  doc_id: string;
  indexed: boolean;
  reason: string | null;
}

export interface DeleteDocumentResponse {
  doc_id: string;
  deleted: boolean;
}
