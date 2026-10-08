// 엘컴화인 MES 시연 영상 — 시나리오 공용 헬퍼 (녹화기는 ~/.claude/skills/test_video_maker/lib — 여기서는 시나리오 쪽 보조만).
//
// · 격리: 녹화는 개발 DB(lcomfine_db)가 아니라 사본 DB(VIDEO_DB, 기본 lcomfine_video)를 쓰는 서버(포트 8031)에 대고 한다.
//   run_all.sh 가 사본을 만들고(VIDEO_DB_READY=1) 끝에 지운다. 시나리오 하나만 돌리면 setup() 이 스스로 만들고 teardown 에서 지운다.
// · 상태: 시나리오 사이에 넘기는 번호(Job · 롤 · LOT · 출하)는 작업 폴더의 state.json 에 적는다.
// · 비밀번호 값은 어디에도 적지 않는다 — .env 의 LCOMFINE_SEED_PASSWORD 를 읽어 type=password 칸에만 넣는다 (G-19).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

export const REPO = process.env.REPO ?? process.cwd();
export const PORT = Number(process.env.VIDEO_PORT ?? 8031);          // 8020 개발 · 8023 QA3 과 겹치지 않게
export const DB = process.env.VIDEO_DB ?? 'lcomfine_video';
export const SOURCE_DB = process.env.LCOMFINE_SOURCE_DB ?? 'lcomfine_db';
export const MARK = '(예시)';
export const STATE_FILE = () => path.join(process.env.VIDEO_STATE_DIR ?? path.join(REPO, 'outputs', 'video', '_work'), 'state.json');

export function dotenv() {
  const out = {};
  const file = path.join(REPO, '.env');
  if (!fs.existsSync(file)) return out;
  for (const raw of fs.readFileSync(file, 'utf8').split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const [k, ...v] = line.split('=');
    out[k.trim()] = v.join('=').trim();
  }
  return out;
}

export function sql(query, db = DB) {
  return execFileSync('psql', ['-h', '/tmp', '-d', db, '-At', '-F', '\t', '-c', query], { encoding: 'utf8' })
    .trim().split('\n').filter(Boolean).map((l) => l.split('\t'));
}
export const sql1 = (query, db) => sql(query, db)[0] ?? null;

export function dbExists(db = DB) {
  return sql(`select 1 from pg_database where datname = '${db}'`, 'postgres').length > 0;
}

// 개발 DB 사본 — pg_dump | psql (개발 서버가 붙어 있어도 된다. createdb -T 는 접속이 있으면 실패한다)
export function makeDbCopy() {
  if (dbExists()) execFileSync('dropdb', ['-h', '/tmp', DB]);
  execFileSync('createdb', ['-h', '/tmp', DB]);
  execFileSync('sh', ['-c', `pg_dump -h /tmp ${SOURCE_DB} | psql -q -h /tmp -d ${DB} -v ON_ERROR_STOP=1 >/dev/null`]);
}
export function dropDbCopy() {
  if (dbExists()) execFileSync('dropdb', ['-h', '/tmp', DB]);
}

export function loadState() {
  const f = STATE_FILE();
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
}
export function saveState(patch) {
  const f = STATE_FILE();
  fs.mkdirSync(path.dirname(f), { recursive: true });
  const cur = loadState();
  const next = { ...cur, ...patch };
  fs.writeFileSync(f, JSON.stringify(next, null, 1));
  return next;
}

// 격리 서버 — 사본 DB · 퀵 로그인 켬 · dev. 비밀(세션 비밀 · 시드 비밀번호)은 .env 에서 앱이 직접 읽는다.
function portBusy(port) {
  return new Promise((resolve) => {
    const s = net.connect({ port, host: '127.0.0.1' });
    s.once('connect', () => { s.destroy(); resolve(true); });
    s.once('error', () => resolve(false));
  });
}
// 앞 편의 서버(uv run uvicorn)가 내려가는 데 잠깐 걸린다 — 포트가 빌 때까지 기다린다(최대 15초)
async function waitPortFree(port) {
  for (let i = 0; i < 100; i++) {
    if (!(await portBusy(port))) return;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`${port} 포트가 15초가 지나도 비지 않는다 — 남은 프로세스를 확인한다 (lsof -i :${port})`);
}

export async function setupServer({ workDir, startServer }) {
  await waitPortFree(PORT);
  const made = !(process.env.VIDEO_DB_READY === '1' && dbExists());
  if (made) makeDbCopy();
  await startServer({
    name: 'mes',
    cmd: 'uv',
    args: ['run', 'uvicorn', 'lcomfine.app.main:app', '--app-dir', 'src', '--port', String(PORT)],
    cwd: REPO,
    env: { LCOMFINE_PG_DSN: `postgresql:///${DB}?host=/tmp`, LCOMFINE_PORT: String(PORT), LCOMFINE_ENV: 'dev', LCOMFINE_QUICK_LOGIN: '1' },
    port: PORT,
    readyUrl: `http://127.0.0.1:${PORT}/health`,
    timeoutMs: 60000,
  });
  const url = `http://127.0.0.1:${PORT}`;
  const seedPassword = dotenv().LCOMFINE_SEED_PASSWORD ?? '';
  return { url, seedPassword, state: loadState(), teardown: async () => { if (made) dropDbCopy(); } };
}

// ── 화면 조작 ────────────────────────────────────────────────────────────
export function helpers(r, env) {
  const { page } = r;
  page.on('dialog', (d) => d.accept());

  const base = env.url;
  const bodyText = async () => (await page.locator('body').innerText()).replace(/\s+/g, ' ');

  // 퀵 로그인 — 로그인 화면의 계정 단추. 실패(401)면 같은 화면이 다시 그려지고 role=alert 에 사유가 있다.
  async function quickLogin(loginId, device = 'web') {
    await r.goto('/login');
    await page.locator('.login-quick').waitFor();
    if (device !== 'web') await r.click(page.locator(`#login-form input[name=device][value=${device}]`));
    const btn = page.locator(`button.quick-btn[value="${loginId}"]`).first();
    if (!(await btn.isVisible())) await r.click(btn.locator('xpath=ancestor::details/summary'));
    const [resp] = await Promise.all([page.waitForNavigation(), r.click(btn)]);
    await r.pause(500);
    return resp ? resp.status() : 0;
  }
  async function logout() {
    await r.goto('/logout');
    await page.locator('#login-form').waitFor();
  }
  // 주소로 열고 HTTP 상태를 돌려준다
  async function open(p) {
    const resp = await page.goto(new URL(p, base).href);
    await r.pause(400);
    return resp ? resp.status() : 0;
  }
  // 왼쪽 메뉴를 눌러 이동 (접힌 대메뉴는 제목을 눌러 편다). 메뉴에 없으면 주소로.
  async function menu(p) {
    const link = page.locator(`nav.side a[href='${p}']`).first();
    if (!(await link.count())) return open(p);
    if (!(await link.isVisible())) {
      await r.click(link.locator('xpath=ancestor::div[contains(@class,"menu-group")]/div[contains(@class,"menu-head")]'));
    }
    const [resp] = await Promise.all([page.waitForNavigation(), r.click(link)]);
    await r.pause(400);
    return resp ? resp.status() : 0;
  }
  // 스캔 = 포커스를 가진 스캔칸에 키보드 입력 + Enter. 포커스가 스캔칸이 아니면 실패(앱의 약속이 깨진 것).
  async function scan(value) {
    const focused = await page.evaluate(() => !!(document.activeElement && document.activeElement.hasAttribute('data-scan')));
    if (!focused) throw new Error(`스캔칸에 포커스가 없다 (${page.url()})`);
    await page.keyboard.type(value, { delay: 60 });
    await r.pause(350);
    const [resp] = await Promise.all([page.waitForNavigation(), page.keyboard.press('Enter')]);
    await r.pause(500);
    return resp ? resp.status() : 0;
  }
  const popup = () => page.locator('#popup-layer');
  const popupOpen = () => popup().isVisible();
  const popupText = async () => ((await popupOpen()) ? (await page.locator('#popup-body').innerText()).trim() : '');
  const popupWarn = async () => (await popupOpen()) && (await page.locator('#popup-layer .popup').getAttribute('class') || '').includes('warn');
  async function closePopup() {
    if (await popupOpen()) await r.click(page.locator('#popup-layer [data-popup-close]'));
    await r.pause(250);
  }
  // 폼의 저장 단추 (form 안의 submit, 또는 form= 속성으로 묶인 바깥 단추)
  function submitButton(formSel, text) {
    const id = formSel.startsWith('#') || formSel.startsWith('form#') ? formSel.replace(/^form/, '').slice(1) : null;
    const parts = [`${formSel} button[type=submit]`];
    if (id) parts.push(`button[form="${id}"]`);
    let loc = page.locator(parts.join(', '));
    if (text) loc = loc.filter({ hasText: text });
    return loc.first();
  }
  async function submit(formSel, text) {
    const [resp] = await Promise.all([page.waitForNavigation(), r.click(submitButton(formSel, text))]);
    await r.pause(600);
    return resp ? resp.status() : 0;
  }
  const field = (formSel, name) => page.locator(`${formSel} [name="${name}"]`).first();
  async function optionValue(selectLoc, text) {
    return selectLoc.locator('option', { hasText: text }).first().getAttribute('value');
  }
  async function selectByText(selectLoc, text) {
    const v = await optionValue(selectLoc, text);
    if (v === null) throw new Error(`선택지 없음: ${text}`);
    await r.select(selectLoc, v);
  }
  // HTML 폼이 아닌 직접 요청 — 권한 차단(403) 시험용
  async function postStatus(p) {
    return page.evaluate(async (u) => (await fetch(u, { method: 'POST', credentials: 'same-origin', headers: { accept: 'application/json' } })).status, p);
  }
  // 폼 POST 를 직접 보낸다(화면 단추가 막혀 있을 때 서버도 막는지 본다) — JSON 응답의 상태와 본문
  async function postForm(p, data) {
    return page.evaluate(async ([u, d]) => {
      const res = await fetch(u, { method: 'POST', credentials: 'same-origin', headers: { accept: 'application/json', 'content-type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(d) });
      let body = null; try { body = await res.json(); } catch {}
      return { status: res.status, body };
    }, [p, data]);
  }
  // 단추·링크를 누르고 화면 전환을 기다린다 — 전환 신호를 놓쳐도(이미 끝났거나 아주 빨랐을 때) 멈추지 않고 로드 완료만 확인한다.
  // 결과는 호출한 쪽이 알림·DB 로 검증한다.
  async function clickNav(loc, { timeout = 4000 } = {}) {
    const nav = page.waitForNavigation({ timeout }).catch(() => null);
    await r.click(loc);
    await nav;
    await page.waitForLoadState('load').catch(() => {});
    await r.pause(500);
  }
  return { bodyText, postForm, clickNav, quickLogin, logout, open, menu, scan, popup, popupOpen, popupText, popupWarn, closePopup, submitButton, submit, field, optionValue, selectByText, postStatus };
}

export const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });   // YYYY-MM-DD
export const plusDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }); };
