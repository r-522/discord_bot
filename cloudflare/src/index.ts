import { Hono } from 'hono';

type Env = {
  DB: D1Database;
  KV: KVNamespace;
  AI: Ai;
  VECTOR_INDEX: VectorizeIndex;
  ASK_TOP_K: string;
  SIMILARITY_THRESHOLD: string;
  MAX_HISTORY: string;
  RATE_LIMIT_PER_MIN: string;
  WORKER_BEARER_TOKEN: string;
  LLM_MODEL: string;
  AI_GATEWAY_BASE_URL: string;
  AI_GATEWAY_API_KEY: string;
  EMBEDDING_MODEL: string;
};

type Chunk = {
  id: string;
  term: string;
  aliases: string;
  content: string;
  source: string;
  category: string;
};

const app = new Hono<{ Bindings: Env }>();

app.use('*', async (c, next) => {
  try {
    const auth = c.req.header('Authorization') || '';
    const expected = `Bearer ${c.env.WORKER_BEARER_TOKEN}`;
    if (auth !== expected) {
      return c.json({ error: 'unauthorized' }, 401);
    }
    await next();
  } catch (_err) {
    return c.json({ error: 'auth_middleware_error' }, 500);
  }
});

async function embedText(env: Env, text: string): Promise<number[]> {
  try {
    const model = env.EMBEDDING_MODEL || '@cf/pfnet/plamo-embedding-1b';
    const result = await env.AI.run(model, { text: [text] }) as { data?: number[][] };
    if (!result?.data?.[0]) throw new Error('embedding_not_found');
    return result.data[0];
  } catch (err) {
    throw new Error(`embedding_error:${(err as Error).message}`);
  }
}

async function fetchChunks(env: Env, ids: string[]): Promise<Chunk[]> {
  try {
    if (!ids.length) return [];
    const placeholders = ids.map(() => '?').join(',');
    const stmt = env.DB.prepare(`SELECT id, term, aliases, content, source, category FROM chunks WHERE id IN (${placeholders})`);
    const res = await stmt.bind(...ids).all<Chunk>();
    return res.results || [];
  } catch (_err) {
    return [];
  }
}

app.post('/search', async (c) => {
  try {
    const body = await c.req.json<{ query?: string; topK?: number }>();
    const query = (body.query || '').trim();
    if (!query) return c.json({ error: 'query_required' }, 400);

    const topK = Number(body.topK || c.env.ASK_TOP_K || 5);
    const vector = await embedText(c.env, query);
    const search = await c.env.VECTOR_INDEX.query(vector, { topK, returnMetadata: true });
    const ids = search.matches.map((m) => m.id);
    const chunks = await fetchChunks(c.env, ids);

    return c.json({
      query,
      matches: search.matches,
      chunks
    });
  } catch (err) {
    return c.json({ error: `search_failed:${(err as Error).message}` }, 500);
  }
});

app.get('/terms', async (c) => {
  try {
    const rows = await c.env.DB.prepare('SELECT term, aliases FROM chunks').all<{ term: string; aliases: string }>();
    const seen = new Set<string>();
    const terms: string[] = [];

    for (const row of rows.results || []) {
      if (row.term && !seen.has(row.term)) {
        seen.add(row.term);
        terms.push(row.term);
      }
      try {
        const aliases = JSON.parse(row.aliases || '[]') as string[];
        for (const a of aliases) {
          if (a && !seen.has(a)) {
            seen.add(a);
            terms.push(a);
          }
        }
      } catch (_e) {
        continue;
      }
    }
    return c.json({ terms });
  } catch (err) {
    return c.json({ error: `terms_failed:${(err as Error).message}` }, 500);
  }
});

app.post('/ask', async (c) => {
  try {
    const body = await c.req.json<{ query?: string; conversationId?: string; topK?: number }>();
    const query = (body.query || '').trim();
    const conversationId = (body.conversationId || '').trim();
    if (!query || !conversationId) return c.json({ error: 'query_and_conversationId_required' }, 400);

    const rateKey = `rate:${conversationId}:${Math.floor(Date.now() / 60000)}`;
    const count = Number((await c.env.KV.get(rateKey)) || '0');
    const limit = Number(c.env.RATE_LIMIT_PER_MIN || '10');
    if (count >= limit) return c.json({ error: 'rate_limited' }, 429);
    await c.env.KV.put(rateKey, String(count + 1), { expirationTtl: 70 });

    const topK = Number(body.topK || c.env.ASK_TOP_K || 5);
    const similarityThreshold = Number(c.env.SIMILARITY_THRESHOLD || '0.4');
    const vector = await embedText(c.env, query);
    const search = await c.env.VECTOR_INDEX.query(vector, { topK, returnMetadata: true });

    const best = search.matches[0];
    if (!best || (best.score ?? 0) < similarityThreshold) {
      return c.json({ answer: 'その用語に関するデータがありません' });
    }

    const ids = search.matches.map((m) => m.id);
    const chunks = await fetchChunks(c.env, ids);
    const historyKey = `conv:${conversationId}`;
    const history = JSON.parse((await c.env.KV.get(historyKey)) || '[]') as Array<{ role: string; content: string }>;

    const systemPrompt = 'あなたはIT用語解説専用です。ナレッジベースの記載のみで回答し、推測しない。箇条書き禁止、Markdown禁止、前置き禁止、締め挨拶禁止。2〜3文で簡潔に述べ、最後に改行して「出典: {source}」を付ける。情報が不足する場合は「その用語に関するデータがありません」のみ返す。';

    const context = chunks.map((x) => `term:${x.term}\nsource:${x.source}\ncontent:${x.content}`).join('\n\n');
    const messages = [
      { role: 'system', content: systemPrompt },
      ...history,
      { role: 'user', content: `質問: ${query}\n\nナレッジ:\n${context}` }
    ];

    const res = await fetch(`${c.env.AI_GATEWAY_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${c.env.AI_GATEWAY_API_KEY}`
      },
      body: JSON.stringify({ model: c.env.LLM_MODEL, temperature: 0.1, messages })
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`llm_error:${res.status}:${txt}`);
    }

    const json = await res.json<any>();
    const answer = json?.choices?.[0]?.message?.content?.trim() || 'その用語に関するデータがありません';

    const maxHistory = Number(c.env.MAX_HISTORY || '10');
    const nextHistory = [...history, { role: 'user', content: query }, { role: 'assistant', content: answer }].slice(-maxHistory);
    await c.env.KV.put(historyKey, JSON.stringify(nextHistory), { expirationTtl: 604800 });

    return c.json({ answer, sources: chunks.map((x) => x.source) });
  } catch (err) {
    return c.json({ error: `ask_failed:${(err as Error).message}` }, 500);
  }
});

export default app;
