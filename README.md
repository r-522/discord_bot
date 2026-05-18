# IT用語解説RAGボット

## 前提環境
- Python 3.11+
- Node.js 20+
- Cloudflareアカウント（Workers / D1 / Vectorize / KV / Workers AI / AI Gateway が有効）
- Discord Bot Token

## ディレクトリ構成
- `cloudflare/`: Workers API
- `ingest/`: Markdown取り込みスクリプト
- `bot/`: Discord Bot
- `gas/`: スリープ回避

## セットアップ手順
1. D1作成とスキーマ適用
   - `cd cloudflare && npm i`
   - `npx wrangler d1 execute IT_TERMS_DB --remote --file=./schema.sql`
2. Vectorizeインデックス作成（2048次元, cosine）
3. `ingest/.env.example` を `.env` にコピーして値を設定
4. `cd ingest && pip install -r requirements.txt && python ingest.py`
5. `cloudflare/wrangler.toml` と Secret を設定し `npx wrangler deploy`
6. `bot/.env.example` をもとにRender環境変数を設定しBotをデプロイ
7. `gas/keepalive.gs` をApps Scriptへ貼り付け、5分トリガーを設定

## 環境変数一覧
- `WORKER_BEARER_TOKEN`: Bot→Workers認証トークン
- `WORKERS_BASE_URL`: Workersの公開URL
- `LLM_MODEL`: AI Gateway経由で使うモデル名
- `AI_GATEWAY_BASE_URL`: AI Gatewayエンドポイント
- `AI_GATEWAY_API_KEY`: AI Gatewayキー
- `DISCORD_BOT_TOKEN`: Discord Botトークン
- `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CF_D1_DATABASE_ID`, `CF_VECTORIZE_INDEX_NAME`

## API確認(curl)
```bash
curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"DNS"}' \
  "$WORKERS_BASE_URL/search"

curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"DNS","conversationId":"12345"}' \
  "$WORKERS_BASE_URL/ask"

curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  "$WORKERS_BASE_URL/terms"
```

## Discordでの使用例
チャンネルで「DNSって何？」と通常発言するだけで、Botがリプライで定義を返します。

## トラブルシューティング
- 401 Unauthorized: Bearerトークン不一致
- 429 rate_limited: 同一conversationIdの1分10回制限に到達
- Botが反応しない: intents (`message_content`) がDeveloper Portalで無効
- 埋め込み失敗: `@cf/pfnet/plamo-embedding-1b` がアカウントで未有効
