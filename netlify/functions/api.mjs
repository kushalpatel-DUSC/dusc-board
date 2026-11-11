// DUSC Action Board — sign-in and data proxy.
// The browser never sees the GitHub token: it signs in with the passcode, gets a signed session,
// and this function reads and writes the board's data files in the private repo on its behalf.
// Settings (Netlify → Site configuration → Environment variables):
//   BOARD_PASSCODE  the passcode you type to sign in (8+ characters)
//   GITHUB_TOKEN    fine-grained token, Contents: read and write, on the data repo only
//   BOARD_REPO      optional, default "kushalpatel-DUSC/dusc-board";  BOARD_BRANCH optional, default "main"
import crypto from 'node:crypto';

const env = k => (globalThis.Netlify && Netlify.env && Netlify.env.get(k)) || process.env[k] || '';
const COLLS = new Set(['cards', 'notes', 'inbox', 'meetings', 'series', 'meta']);
const SESSION_DAYS = 180;
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
const sleep = ms => new Promise(r => setTimeout(r, ms));

function signingKey() { return crypto.createHmac('sha256', env('GITHUB_TOKEN')).update('dusc-board-session:' + env('BOARD_PASSCODE')).digest(); }
function sign(exp) { return crypto.createHmac('sha256', signingKey()).update(String(exp)).digest('base64url'); }
function makeSession() { const exp = Date.now() + SESSION_DAYS * 86400000; return exp + '.' + sign(exp); }
function validSession(tok) {
  const [exp, sig] = String(tok || '').split('.'); if (!exp || !sig || !/^\d+$/.test(exp) || Number(exp) < Date.now()) return false;
  const a = Buffer.from(sig), b = Buffer.from(sign(exp)); return a.length === b.length && crypto.timingSafeEqual(a, b);
}
function samePass(given) {
  const a = crypto.createHash('sha256').update(String(given)).digest(), b = crypto.createHash('sha256').update(env('BOARD_PASSCODE')).digest();
  return crypto.timingSafeEqual(a, b);
}

export default async (req) => {
  const url = new URL(req.url); const path = url.pathname.replace(/^\/api\/?/, '');
  if (!env('GITHUB_TOKEN') || !env('BOARD_PASSCODE')) return json(503, { error: 'setup', message: 'The board is not set up yet: add BOARD_PASSCODE and GITHUB_TOKEN in Netlify, then redeploy.' });
  if (env('BOARD_PASSCODE').length < 8) return json(503, { error: 'setup', message: 'BOARD_PASSCODE must be at least 8 characters.' });

  if (path === 'login' && req.method === 'POST') {
    let body = {}; try { body = await req.json(); } catch (e) {}
    if (typeof body.passcode !== 'string' || !samePass(body.passcode)) { await sleep(900); return json(401, { error: 'passcode' }); }
    return json(200, { session: makeSession(), days: SESSION_DAYS });
  }

  const m = /^data\/([a-z]+)\.json$/.exec(path);
  if (!m || !COLLS.has(m[1])) return json(404, { error: 'not_found' });
  const auth = req.headers.get('authorization') || '';
  if (!validSession(auth.replace(/^Bearer\s+/i, ''))) return json(401, { error: 'session' });

  const repo = env('BOARD_REPO') || 'kushalpatel-DUSC/dusc-board'; const branch = env('BOARD_BRANCH') || 'main';
  const gh = `https://api.github.com/repos/${repo}/contents/data/${m[1]}.json`;
  const headers = { 'authorization': 'Bearer ' + env('GITHUB_TOKEN'), 'accept': 'application/vnd.github+json', 'x-github-api-version': '2022-11-28', 'user-agent': 'dusc-board' };
  let r;
  if (req.method === 'GET') {
    r = await fetch(gh + '?ref=' + encodeURIComponent(branch), { headers });
  } else if (req.method === 'PUT') {
    let body = {}; try { body = await req.json(); } catch (e) { return json(400, { error: 'bad_json' }); }
    if (typeof body.content !== 'string') return json(400, { error: 'bad_body' });
    const out = { message: String(body.message || 'board: update').slice(0, 200), content: body.content, branch }; if (body.sha) out.sha = body.sha;
    r = await fetch(gh, { method: 'PUT', headers: { ...headers, 'content-type': 'application/json' }, body: JSON.stringify(out) });
  } else return json(405, { error: 'method' });
  // GitHub's own 401/403 means the stored token is bad, not the visitor's session: report it as a server problem
  if (r.status === 401 || r.status === 403) return json(502, { error: 'github_token', message: 'GitHub refused the stored token. Replace GITHUB_TOKEN in Netlify.' });
  const j = await r.json().catch(() => ({}));
  if (req.method === 'GET') return json(r.status, r.ok ? { sha: j.sha, content: j.content } : { error: 'github', status: r.status });
  return json(r.status, r.ok ? { content: { sha: j.content && j.content.sha } } : { error: 'github', status: r.status });
};

export const config = { path: '/api/*' };
