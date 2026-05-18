-- IT用語チャンク保存テーブル
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  term TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '[]',
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  category TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_term ON chunks(term);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);

-- 更新時刻自動更新トリガー
CREATE TRIGGER IF NOT EXISTS trg_chunks_updated_at
AFTER UPDATE ON chunks
FOR EACH ROW
BEGIN
  UPDATE chunks SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
