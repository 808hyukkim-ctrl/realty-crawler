// 표·열 준비를 적은 왕복으로 (2026-10-14). 전에는 ensure* 가 CREATE/ALTER 를 하나씩 순서대로 보내서
// 새로 뜬 워커의 첫 요청마다 13~16번 왕복했다 → CREATE ... IF NOT EXISTS 는 batch 하나, 열 추가는 PRAGMA 로 빠진 것만.
export async function prepareSchema(db: D1Database, creates: (string | D1PreparedStatement)[], columns: Record<string, string[]> = {}): Promise<void> {
  if (creates.length) await db.batch(creates.map((s) => (typeof s === "string" ? db.prepare(s) : s)));
  const tables = Object.keys(columns);
  if (!tables.length) return;
  const infos = await Promise.all(tables.map((t) => db.prepare(`PRAGMA table_info(${t})`).all()));
  const alters: D1PreparedStatement[] = [];
  tables.forEach((t, i) => {
    const have = new Set(((infos[i]?.results ?? []) as any[]).map((r) => String(r.name)));
    for (const def of columns[t]) { const col = def.trim().split(/\s+/)[0]; if (!have.has(col)) alters.push(db.prepare(`ALTER TABLE ${t} ADD COLUMN ${def}`)); }
  });
  for (const a of alters) { try { await a.run(); } catch { /* 동시 요청이 먼저 추가했을 수 있다 */ } }
}
