// 비밀번호 검증 (index.ts 의 verifyPassword 와 같은 포맷: pbkdf2$iter$saltHex$hashHex) — 당근 광고자동화 로그인이 같이 쓴다 (2026-10-08)
export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = String(stored || "").split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2") return false;
  const iterations = parseInt(parts[1], 10);
  const salt = fromHex(parts[2]);
  const expected = parts[3];
  const hash = await pbkdf2(password, salt, iterations);
  return toHex(hash) === expected;
}

async function pbkdf2(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt: salt as unknown as ArrayBuffer, iterations, hash: "SHA-256" }, keyMaterial, 256);
  return new Uint8Array(bits);
}
function toHex(buf: Uint8Array): string { return Array.from(buf).map((b) => b.toString(16).padStart(2, "0")).join(""); }
function fromHex(hex: string): Uint8Array { const out = new Uint8Array(hex.length / 2); for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16); return out; }
