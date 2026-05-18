import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict

import httpx
from dotenv import load_dotenv
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

load_dotenv()


def make_id(term: str, content: str) -> str:
    return hashlib.sha256(f"{term}:{content}".encode("utf-8")).hexdigest()


def split_markdown(text: str) -> List[Dict[str, str]]:
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "term"), ("##", "section")])
    docs = header_splitter.split_text(text)
    child_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = []
    for doc in docs:
        term = doc.metadata.get("term", "不明用語")
        section = doc.metadata.get("section", "")
        parts = child_splitter.split_text(doc.page_content)
        for p in parts:
            chunks.append({"term": term, "section": section, "content": p})
    return chunks


def main() -> None:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    vectorize_name = os.getenv("CF_VECTORIZE_INDEX_NAME", "")
    d1_db_id = os.getenv("CF_D1_DATABASE_ID", "")
    model = os.getenv("CF_EMBEDDING_MODEL", "@cf/pfnet/plamo-embedding-1b")
    source = os.getenv("SOURCE_LABEL", "基本情報技術者試験シラバス Ver9.0")
    category = os.getenv("CATEGORY_DEFAULT", "テクノロジ系")

    if not all([account_id, api_token, vectorize_name, d1_db_id]):
        raise RuntimeError("必須環境変数が不足しています")

    md_files = list(Path("sample_data").glob("*.md"))
    if not md_files:
        raise FileNotFoundError("sample_data に Markdown がありません")

    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30.0) as client:
        for md in md_files:
            raw = md.read_text(encoding="utf-8")
            for chunk in split_markdown(raw):
                term = chunk["term"]
                content = chunk["content"].strip()
                if not content:
                    continue
                aliases = [term]
                chunk_id = make_id(term, content)

                try:
                    emb_res = client.post(
                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
                        headers=headers,
                        json={"text": [content]},
                    )
                    emb_res.raise_for_status()
                    vector = emb_res.json()["result"]["data"][0]
                except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
                    print(f"embedding失敗: {chunk_id}: {e}")
                    continue

                try:
                    vec_res = client.post(
                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes/{vectorize_name}/upsert",
                        headers=headers,
                        json={
                            "vectors": [
                                {
                                    "id": chunk_id,
                                    "values": vector,
                                    "metadata": {"term": term, "source": source, "category": category},
                                }
                            ]
                        },
                    )
                    vec_res.raise_for_status()
                except httpx.HTTPError as e:
                    print(f"vectorize失敗: {chunk_id}: {e}")
                    continue

                sql = "INSERT OR REPLACE INTO chunks (id, term, aliases, content, source, category) VALUES (?, ?, ?, ?, ?, ?)"
                try:
                    d1_res = client.post(
                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{d1_db_id}/query",
                        headers=headers,
                        json={"sql": sql, "params": [chunk_id, term, json.dumps(aliases, ensure_ascii=False), content, source, category]},
                    )
                    d1_res.raise_for_status()
                except httpx.HTTPError as e:
                    print(f"D1保存失敗: {chunk_id}: {e}")
                    continue

                print(f"投入成功: {chunk_id} {term}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, FileNotFoundError, PermissionError, OSError, ValueError) as e:
        print(f"致命的エラー: {e}")
