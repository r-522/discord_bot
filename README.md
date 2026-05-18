# IT用語解説RAGボット

基本情報技術者試験の用語・一般IT用語を対象に、Cloudflare上のRAG基盤とDiscord Botで「推測なし・出典付き」の説明を返す構成です。

## 1. このREADMEで分かること
- どのサービスで何を作成し、どこからID/トークンを取得するか
- 初期セットアップの順序
- 動作確認の具体的なコマンド
- 詰まりやすいポイントの対処

## 2. 全体構成
- Discord Bot（Render想定）がメッセージを監視
- 検知した用語を Cloudflare Workers `/ask` に送信
- Workers が Vectorize + D1 + KV を使って検索と会話管理
- AI Gateway 経由で LLM から回答生成

## 3. 前提環境
- Python 3.11+
- Node.js 20+
- npm 10+
- Cloudflareアカウント（Workers / D1 / Vectorize / KV / Workers AI / AI Gateway を利用）
- Discordアカウント（Developer PortalでBot作成）
- Renderアカウント（Bot常駐先）
- （任意）Googleアカウント（Apps Scriptでkeepalive）

## 4. リポジトリ構成
```text
project-root/
├── cloudflare/
│   ├── src/index.ts
│   ├── schema.sql
│   ├── wrangler.toml
│   └── package.json
├── ingest/
│   ├── ingest.py
│   ├── requirements.txt
│   ├── .env.example
│   └── sample_data/
├── bot/
│   ├── main.py
│   ├── detector.py
│   ├── requirements.txt
│   ├── Procfile
│   └── .env.example
├── gas/
│   └── keepalive.gs
└── README.md
```

## 5. 先に作るべきCloudflareリソース（取得場所つき）
以下を**先に**作ると、以降の設定がスムーズです。

### 5.1 Cloudflare Account ID
- 取得場所: Cloudflare Dashboard 右サイドバーの「Account ID」
- 用途: `ingest/.env` の `CLOUDFLARE_ACCOUNT_ID`

### 5.2 API Token
- 作成場所: `My Profile` → `API Tokens` → `Create Token`
- 推奨: カスタムトークン（Workers AI / D1 / Vectorize を操作できる権限）
- 用途: `ingest/.env` の `CLOUDFLARE_API_TOKEN`

### 5.3 D1 Database
- 作成例:
  ```bash
  cd cloudflare
  npx wrangler d1 create it_terms_db
  ```
- 取得するもの:
  - `database_id`（コマンド実行結果）
- 反映先:
  - `cloudflare/wrangler.toml` の `database_id`
  - `ingest/.env` の `CF_D1_DATABASE_ID`

### 5.4 Vectorize Index
- 作成例（2048次元, cosine）:
  ```bash
  npx wrangler vectorize create it-terms-index --dimensions=2048 --metric=cosine
  ```
- 取得するもの:
  - index名（ここでは `it-terms-index`）
- 反映先:
  - `cloudflare/wrangler.toml` の `index_name`
  - `ingest/.env` の `CF_VECTORIZE_INDEX_NAME`

### 5.5 KV Namespace
- 作成例:
  ```bash
  npx wrangler kv namespace create KV
  ```
- 取得するもの:
  - namespace ID
- 反映先:
  - `cloudflare/wrangler.toml` の `[[kv_namespaces]].id`

### 5.6 Workers AI
- 使用モデル: `@cf/pfnet/plamo-embedding-1b`
- 用途:
  - ingest時の埋め込み
  - Workers内の埋め込み生成

### 5.7 AI Gateway
- 作成場所: Cloudflare Dashboard → AI Gateway
- 取得するもの:
  - Gateway Base URL
  - Gateway API Key
- 反映先:
  - Workers Secret `AI_GATEWAY_BASE_URL`
  - Workers Secret `AI_GATEWAY_API_KEY`

## 6. Discord Bot情報の取得方法
### 6.1 Bot Token
- 作成場所: Discord Developer Portal → Applications → Bot
- 取得するもの: Bot Token
- 反映先: Render環境変数 `DISCORD_BOT_TOKEN`

### 6.2 Intents
Developer Portal の Bot 設定で以下を有効化:
- Message Content Intent
- Server Members Intent は不要（この実装では未使用）

### 6.3 OAuth2招待
- OAuth2 → URL Generator で `bot` スコープ
- Bot Permissions は最低限 `Send Messages` / `Read Message History` / `View Channels`

## 7. セットアップ手順（推奨順）

### Step 0: 依存インストール
```bash
cd cloudflare && npm i
cd ../ingest && python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 1: D1スキーマ適用
```bash
cd cloudflare
npx wrangler d1 execute it_terms_db --remote --file=./schema.sql
```

### Step 2: `wrangler.toml` を埋める
- `database_id`
- `[[kv_namespaces]].id`
- 必要に応じて `name` 等

### Step 3: Workers Secret設定
```bash
npx wrangler secret put WORKER_BEARER_TOKEN
npx wrangler secret put LLM_MODEL
npx wrangler secret put AI_GATEWAY_BASE_URL
npx wrangler secret put AI_GATEWAY_API_KEY
npx wrangler secret put EMBEDDING_MODEL
```

### Step 4: ingest用 `.env` 作成
```bash
cd ../ingest
cp .env.example .env
```
`.env` に以下を設定:
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `CF_VECTORIZE_INDEX_NAME`
- `CF_D1_DATABASE_ID`
- `CF_EMBEDDING_MODEL`（通常は `@cf/pfnet/plamo-embedding-1b`）
- `SOURCE_LABEL`
- `CATEGORY_DEFAULT`

### Step 5: ナレッジ投入
```bash
python ingest.py
```

### Step 6: Workersデプロイ
```bash
cd ../cloudflare
npx wrangler deploy
```

### Step 7: RenderへBotデプロイ
- ルートディレクトリ: `bot`
- Start command: `python main.py`
- 環境変数（`bot/.env.example` 参照）
  - `DISCORD_BOT_TOKEN`
  - `WORKERS_BASE_URL`（例: `https://it-term-rag-worker.<subdomain>.workers.dev`）
  - `WORKER_BEARER_TOKEN`（Workersと同一）
  - `DICT_RELOAD_SECONDS`（推奨3600）
  - `USER_COOLDOWN_SECONDS`（推奨30）
  - `CHANNEL_COOLDOWN_SECONDS`（推奨10）
  - `HTTP_PORT`（Renderが指定するPORTに合わせる）

### Step 8: GAS keepalive（任意）
- `gas/keepalive.gs` のURLをRenderの `/healthz` に置換
- Apps Scriptトリガーで5分間隔実行

## 8. 環境変数一覧（最終版）

### Workers（Secret / Vars）
- `WORKER_BEARER_TOKEN`: Bot→Workers認証
- `LLM_MODEL`: AI Gateway経由で使うモデル名
- `AI_GATEWAY_BASE_URL`: AI GatewayのベースURL
- `AI_GATEWAY_API_KEY`: AI Gatewayキー
- `EMBEDDING_MODEL`: 埋め込みモデル名
- `ASK_TOP_K`: 検索件数（既定5）
- `SIMILARITY_THRESHOLD`: 閾値（既定0.40）
- `MAX_HISTORY`: 会話履歴保持件数（既定10）
- `RATE_LIMIT_PER_MIN`: 1分あたり制限（既定10）

### ingest（`.env`）
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `CF_VECTORIZE_INDEX_NAME`
- `CF_D1_DATABASE_ID`
- `CF_EMBEDDING_MODEL`
- `SOURCE_LABEL`
- `CATEGORY_DEFAULT`

### bot（Render環境変数）
- `DISCORD_BOT_TOKEN`
- `WORKERS_BASE_URL`
- `WORKER_BEARER_TOKEN`
- `DICT_RELOAD_SECONDS`
- `USER_COOLDOWN_SECONDS`
- `CHANNEL_COOLDOWN_SECONDS`
- `HTTP_PORT`

## 9. 動作確認

### 9.1 `/terms`
```bash
curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  "$WORKERS_BASE_URL/terms"
```

### 9.2 `/search`
```bash
curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"DNS"}' \
  "$WORKERS_BASE_URL/search"
```

### 9.3 `/ask`
```bash
curl -H "Authorization: Bearer $WORKER_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"DNS","conversationId":"sample-thread-001"}' \
  "$WORKERS_BASE_URL/ask"
```

### 9.4 Discord
- Discordチャンネルで通常発言: `DNSって何？`
- Botがリプライで2〜3文＋出典を返せばOK

## 10. よくあるエラーと対処
- 401 Unauthorized
  - `WORKER_BEARER_TOKEN` 不一致（Bot側とWorkers Secret側を同じ値に）
- 429 rate_limited
  - 同一 `conversationId` で1分10回超過
- Botが反応しない
  - Developer Portalで `Message Content Intent` が無効
  - `WORKERS_BASE_URL` の誤り
- ingestで埋め込み失敗
  - `CLOUDFLARE_API_TOKEN` 権限不足
  - `@cf/pfnet/plamo-embedding-1b` が利用不可
- `/ask` が500
  - `AI_GATEWAY_BASE_URL` / `AI_GATEWAY_API_KEY` / `LLM_MODEL` の不整合

## 11. セキュリティ注意
- `.env` はコミットしない
- Token / API Key をログに出さない
- `WORKER_BEARER_TOKEN` は十分長いランダム値を使用
