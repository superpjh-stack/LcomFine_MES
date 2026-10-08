// 시연 1 · 관리자 — 퀵 로그인 → 메인 → 품목 등록 → 작업지시 등록·작업지시서 → 사용자 등록 → 권한 표 → 접근 로그
import { setupServer, helpers, saveState, MARK, plusDays, sql1 } from './lib/mes.mjs';

export const config = { voice: 'Yuna', out: 'outputs/video/시연-01-관리자.mp4' };
export const setup = setupServer;

export default async function scenario(r, env) {
  const { page, say, settle, scene, box, check } = r;
  const h = helpers(r, env);
  const ITEM = 'VID-FG-01';

  await r.goto('/login');
  await page.locator('.login-quick').waitFor();
  await r.card(`<h2>엘컴화인 MES · Job-Lot-Roll 계보</h2><h1>시연 1 · 관리자</h1>
    <h2>퀵 로그인 → 기준정보 → 작업지시 · 작업지시서 → 사용자 · 권한 · 접근 로그</h2>
    <h2 style="font-size:19px;color:#93c5fd">화면의 데이터는 전부 (예시) · 녹화는 개발 DB 사본으로 한다</h2>`);
  await r.start();
  scene('시작');
  await say('엘컴화인 MES 시연 첫 번째, 관리자 편입니다. 로그인부터 기준정보, 작업지시, 시스템 관리까지 관리자가 하는 일을 실제 화면에서 확인합니다.',
    '시연 1 · 관리자 — 로그인 · 기준정보 · 작업지시 · 시스템 관리');
  await settle(0.5);
  await r.card(null);

  // ── 1. 로그인 화면 · 퀵 로그인 ──
  scene('1 · 로그인');
  await say('로그인 화면입니다. 왼쪽은 아이디와 비밀번호를 넣는 보통 로그인, 오른쪽은 개발 테스트 환경에서만 보이는 퀵 로그인 패널입니다.',
    '왼쪽: 보통 로그인 · 오른쪽: 퀵 로그인 패널(개발·테스트 환경에서만)');
  await box(page.locator('.login-card'), 1800);
  await box(page.locator('.login-quick'), 2200);
  await say('역할마다 카드가 하나씩 있고, 그 역할이 대메뉴 열두 개 중 몇 개를 입력하고 몇 개를 조회할 수 있는지 권한 표 그대로 보여 줍니다. 비밀번호 값은 이 화면 어디에도 없습니다.',
    '역할 4 카드 — 대메뉴 12 중 입력·조회·없음 칸 수(DB 권한 표) · 비밀번호 값은 HTML 에 없다');
  const roles = await page.locator('.quick-role').count();
  await check(`퀵 로그인 패널에 역할 ${roles}개 카드`, roles === 4, String(roles));
  await check('화면 HTML 에 시드 비밀번호 값 없음', !(await page.content()).includes(env.seedPassword) && env.seedPassword.length > 0);
  await box(page.locator('.quick-role[data-role=ADMIN]'), 2000);
  await settle(0.3);
  await say('관리자 단추를 누르면 비밀번호 입력 없이 관리자 계정으로 들어갑니다.', '관리자 (예시) admin 단추 → 비밀번호 입력 없이 로그인');
  const st = await h.quickLogin('admin');
  await check('관리자 퀵 로그인 → 메인 화면', st === 200 && new URL(page.url()).pathname === '/', `${st} ${page.url()}`);

  // ── 2. 메인 ──
  scene('2 · 메인');
  await say('메인입니다. 왼쪽 메뉴와 가운데 카드는 이 역할의 권한 표로 그려집니다. 관리자는 열두 대메뉴를 모두 열 수 있습니다.',
    '메인 — 메뉴·카드는 역할의 권한 표(DB)로 그려진다 · 관리자: 대메뉴 12 전부');
  await box(page.locator('nav.side'), 1800);
  const cards = await page.locator('.cards .card').count();
  await box(page.locator('.cards').first(), 1800);
  await check(`메인 카드 ${cards}개 = 대메뉴 12`, cards === 12, String(cards));
  const head = (await page.locator('.main h2').first().innerText()).replace(/\s+/g, ' ');
  await check('로그인 사용자 표시 — 관리자 (예시) · 관리자', /관리자 \(예시\)/.test(head) && /관리자/.test(head), head);

  // ── 3. 기준정보 · 품목 등록 ──
  scene('3 · 기준정보');
  await settle(0.2);
  await h.menu('/bas/items');
  await say('기준정보 관리의 품목입니다. 시연에 쓸 제품 하나를 등록합니다. 코드와 이름, 구분, 규격, 단위를 넣습니다.',
    '품목 등록 — 코드 VID-FG-01 · 이름 「시연 제품 (예시)」 · 구분 제품 · 600mm · m');
  const F = 'form#master-form';
  await r.type(h.field(F, 'item_code'), ITEM);
  await r.type(h.field(F, 'item_name'), `시연 제품 ${MARK}`);
  await r.select(h.field(F, 'item_type'), '제품');
  await r.type(h.field(F, 'spec'), `600mm ${MARK}`);
  await r.type(h.field(F, 'unit'), 'm');
  await settle(0.2);
  await say('저장하면 알림이 뜨고 목록에 바로 나타납니다.');
  await h.submit(F);
  const msg = await h.popupText();
  await check('품목 저장 알림', (await h.popupOpen()) && !(await h.popupWarn()), msg);
  await box(h.popup().locator('.popup'), 1500);
  await h.closePopup();
  await say('목록은 한 쪽에 열 줄씩 보여 주므로 코드로 조회해 확인합니다.', '코드로 조회 → 방금 등록한 행');
  await r.type(h.field('form#screen-search', 'code'), ITEM);
  await h.submit('form#screen-search', '조회');
  const row = page.locator('table.grid tr:not([hidden])', { hasText: ITEM }).first();
  await box(row, 1800);
  await check(`조회 결과에 ${ITEM} 행`, (await row.count()) === 1 && /시연 제품/.test(await row.innerText()));

  // ── 4. 작업지시 ──
  scene('4 · 작업지시');
  await settle(0.2);
  await h.menu('/job/orders');
  await say('작업지시 등록입니다. 방금 만든 품목에 고객, 판사양, 아니록스, 잉크조성, 설비, 수량, 납기를 지정합니다. 잡 번호는 채번 규칙이 저장할 때 자동으로 만듭니다.',
    '작업지시 등록 — 품목·고객·판사양·아니록스·잉크조성·설비·수량·납기 · Job 번호는 채번 규칙이 자동 생성');
  const J = 'form#job-form';
  await page.locator(J).scrollIntoViewIfNeeded();
  await h.selectByText(h.field(J, 'item_id'), ITEM);
  await h.selectByText(h.field(J, 'customer_id'), 'EX-CU-01');
  await h.selectByText(h.field(J, 'plate_spec_id'), 'EX-PL-01');
  await h.selectByText(h.field(J, 'anilox_id'), 'EX-AN-01');
  await h.selectByText(h.field(J, 'ink_formula_id'), 'EX-INK-01');
  await h.selectByText(h.field(J, 'equipment_id'), 'EX-EQ-01');
  await r.type(h.field(J, 'order_qty'), '3000');
  await r.fill(h.field(J, 'due_date'), plusDays(7));
  await r.type(h.field(J, 'note'), `시연 ${MARK}`);
  await settle(0.2);
  await h.submit(J);
  const jmsg = await h.popupText();
  const jrow = sql1(`select j.job_no, j.status from job j join item i on i.item_id = j.item_id where i.item_code = '${ITEM}' order by job_id desc limit 1`);
  await check('작업지시 저장 알림', (await h.popupOpen()) && !(await h.popupWarn()), jmsg);
  await check(`Job 번호 채번 ${jrow?.[0]} (J+날짜+일련) · 상태 ${jrow?.[1]}`, !!jrow && /^J\d{6}-\d{3}$/.test(jrow[0]) && jrow[1] === '등록', JSON.stringify(jrow));
  const jobNo = jrow[0];
  saveState({ jobNo, item: ITEM });
  await say(`작업지시 ${jobNo.replace(/(\d)/g, '$1 ')} 가 만들어졌습니다. 작업지시서를 출력해 보겠습니다. 바코드는 외부 라이브러리 없이 인라인 SVG 로 그립니다.`,
    `Job ${jobNo} 등록 완료 → 작업지시서 출력 (Code128 바코드 = 인라인 SVG)`);
  await h.closePopup();
  const printLink = page.locator(`a[href='/job/orders/${jobNo}/print']`).first();
  await Promise.all([page.waitForNavigation(), r.click(printLink)]);
  await r.pause(800);
  const svg = await page.locator('svg').count();
  await box(page.locator('svg').first(), 2000);
  await check(`작업지시서에 Job 번호와 바코드 SVG ${svg}개`, svg >= 1 && (await h.bodyText()).includes(jobNo), String(svg));
  await settle(0.5);

  // ── 5. 사용자 등록 ──
  scene('5 · 사용자');
  await h.open('/sys/users');
  await say('시스템 관리의 사용자입니다. 검사원 계정을 하나 만듭니다. 초기 비밀번호는 가려진 칸에 들어가고 화면에 보이지 않습니다. 저장은 해시만 합니다.',
    '사용자 등록 — vid_qc · 시연 검사원 (예시) · 역할 품질 · 비밀번호는 PBKDF2 해시로만 저장');
  const U = 'form#user-form';
  await page.locator(U).scrollIntoViewIfNeeded();
  await r.type(h.field(U, 'login_id'), 'vid_qc');
  await r.type(h.field(U, 'user_name'), `시연 검사원 ${MARK}`);
  await h.selectByText(h.field(U, 'role_code'), '품질');
  await r.fill(h.field(U, 'password'), env.seedPassword);
  await settle(0.2);
  await h.submit(U);
  const umsg = await h.popupText();
  const urow = sql1(`select role_code, status, password_hash like 'pbkdf2_sha256$%' from sys_user where login_id = 'vid_qc'`);
  await check('사용자 저장 알림', (await h.popupOpen()) && !(await h.popupWarn()), umsg);
  await check('vid_qc = 품질(QC) · 정상 · 해시 저장', !!urow && urow[0] === 'QC' && urow[1] === '정상' && urow[2] === 't', JSON.stringify(urow));
  await h.closePopup();

  // ── 6. 권한 표 ──
  scene('6 · 권한');
  await h.menu('/sys/permissions');
  await say('권한 표입니다. 역할 네 개 곱하기 대메뉴 열두 개, 마흔여덟 칸이 전부 데이터입니다. 코드에 역할을 박아 두지 않아서 여기서 바꾸면 다음 요청부터 바로 적용됩니다.',
    '권한 표 — 역할 4 × 대메뉴 12 = 48칸 전부 DB 데이터 · 바꾸면 다음 요청부터 적용');
  const cells = await page.locator('.perm-cell').count();
  await box(page.locator('table.perm'), 2500);
  const lv = { 입력: await page.locator('.perm-cell[data-level=입력]').count(), 조회: await page.locator('.perm-cell[data-level=조회]').count(), 없음: await page.locator('.perm-cell[data-level=없음]').count() };
  await check(`권한 칸 ${cells} = 48 (입력 ${lv.입력} · 조회 ${lv.조회} · 없음 ${lv.없음})`, cells === 48 && lv.입력 + lv.조회 + lv.없음 === 48, JSON.stringify(lv));

  // ── 7. 접근 로그 ──
  scene('7 · 접근 로그');
  await settle(0.2);
  await h.menu('/sys/logs');
  await say('접근 로그입니다. 로그인, 화면 조회, 변경이 누가 언제 했는지와 함께 남습니다. 구분을 로그인으로 좁혀 보면 방금의 퀵 로그인도 그렇게 표시되어 남아 있습니다.',
    '접근 로그 — 로그인·조회·변경 · 구분=로그인으로 조회 → 「퀵 로그인」 표시');
  const S = 'form#screen-search';
  await r.select(h.field(S, 'log_type'), '로그인');
  await h.submit(S, '조회');
  const logRow = page.locator('table.grid tr', { hasText: '퀵 로그인' }).first();
  await box(logRow, 2200);
  await check('접근 로그에 「로그인 성공 · 퀵 로그인」 행', (await logRow.count()) === 1 && /admin/.test(await logRow.innerText()));
  await settle(0.3);

  // ── 결과 ──
  scene('결과');
  await r.resultCard('시연 1 · 관리자 — 검증 결과');
  await say('관리자 편의 검증은 모두 통과했습니다. 다음 편에서는 현장 계정으로 입고부터 작업 실적까지 현장 POP 화면을 봅니다.',
    '검증 전부 통과 · 다음: 시연 2 현장 POP (입고 → 검사 → 작업 실적 → 투입 → 정지·폐기 → 종료 → 라벨)');
  await r.stop(1.2);
}
