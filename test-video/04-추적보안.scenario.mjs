// 시연 4 · 추적·현황·보안 — 역방향·정방향 추적 → 롤 이력 → Job-Lot-Roll 매핑 → 불량 집계 → 실적 현황 → 현황판 → 중지 계정 401 → 현장 403 → 접근 로그
import { setupServer, helpers, loadState, sql1 } from './lib/mes.mjs';

export const config = { voice: 'Yuna', out: 'outputs/video/시연-04-추적보안.mp4' };
export const setup = setupServer;

export default async function scenario(r, env) {
  const { page, say, settle, scene, box, check } = r;
  const h = helpers(r, env);
  const { jobNo, lotNo, printRoll, slitRolls, spliceRoll, shipNo } = loadState();
  if (!shipNo || !lotNo) throw new Error('시연 3 까지의 상태가 없다 — 시연 1~3 을 먼저 돌린다');
  const spoken = (no) => no.replace(/(\d)/g, '$1 ');

  await r.goto('/login');
  await page.locator('.login-quick').waitFor();
  await r.card(`<h2>엘컴화인 MES · Job-Lot-Roll 계보</h2><h1>시연 4 · 추적 · 현황 · 보안</h1>
    <h2>출하 LOT → 원재료 LOT 역방향 추적 · 정방향 · 롤 이력 · 집계 · 현황판 · 권한 차단</h2>
    <h2 style="font-size:19px;color:#93c5fd">추적·집계는 조회일 뿐 — 어떤 테이블에도 쓰지 않는다</h2>`);
  await r.start();
  scene('시작');
  await say('마지막 네 번째, 추적과 현황, 보안 편입니다. 이 시스템의 완료 기준인 출하 롤 하나에서 원재료 로트까지 거슬러 올라가는 추적을 먼저 봅니다.',
    '시연 4 — 완료 기준: 출하 롤 하나에서 원재료 LOT 까지');
  await settle(0.5);
  await r.card(null);

  // ── 1. 역방향 추적 ──
  scene('1 · 역방향 추적');
  await h.quickLogin('admin');
  await h.open('/trc/trace');
  await say(`출하 로트 ${spoken(shipNo)} 번호를 넣고 역방향 추적을 누릅니다. 롤 지니얼로지를 거슬러 올라가는 조회일 뿐, 아무 테이블에도 쓰지 않습니다.`,
    `출하 LOT ${shipNo} → 역방향 추적 (roll_genealogy 를 거슬러 올라가는 조회)`);
  await page.keyboard.type(shipNo, { delay: 60 });
  await h.clickNav(page.locator('button[formaction="/trc/trace/backward"]'));
  await page.locator('.main').first().waitFor();
  const back = await h.bodyText();
  const need = [slitRolls[0], printRoll, lotNo];
  const miss = need.filter((x) => !back.includes(x));
  await box(page.locator('.main').first(), 2600);
  await check(`역방향: 출하 ${shipNo} ← 슬리팅 롤 ${slitRolls[0]} ← 인쇄 롤 ${printRoll} ← 원재료 LOT ${lotNo}`, miss.length === 0, '없는 번호 ' + miss.join(','));
  await say('출하 로트에서 슬리팅 롤, 인쇄 롤, 그리고 투입된 원재료 로트까지 한 화면에 이어집니다. 불합격이라 담기지 않은 스플라이스 롤은 당연히 없습니다.',
    `출하 → 슬리팅 롤 → 인쇄 롤 → 원재료 LOT · 담기지 않은 ${spliceRoll} 은 없다`);
  await check(`담기지 않은 불합격 롤 ${spliceRoll} 은 역방향 결과에 없다`, !back.includes(spliceRoll));

  // ── 2. 정방향 추적 ──
  scene('2 · 정방향 추적');
  await settle(0.2);
  await h.open('/trc/trace');
  await say(`이번에는 원재료 로트 ${spoken(lotNo)} 에서 내려갑니다. 그 로트가 들어간 롤과 나뉜 롤, 합쳐진 롤, 출하까지 전부 나옵니다.`,
    `원재료 LOT ${lotNo} → 정방향 추적 — 투입된 롤 · 슬리팅 · splice · 출하 전부`);
  await page.keyboard.type(lotNo, { delay: 60 });
  await h.clickNav(page.locator('button[formaction="/trc/trace/forward"]'));
  await page.locator('.main').first().waitFor();
  const fwd = await h.bodyText();
  const need2 = [printRoll, ...slitRolls, spliceRoll, shipNo];
  const miss2 = need2.filter((x) => !fwd.includes(x));
  await box(page.locator('.main').first(), 2600);
  await check(`정방향: LOT → 인쇄 롤 → 슬리팅 롤 3 → splice 롤 → 출하 ${shipNo}`, miss2.length === 0, '없는 번호 ' + miss2.join(','));

  // ── 3. 롤 이력 ──
  scene('3 · 롤 이력');
  await settle(0.2);
  await h.open(`/rll/history?no=${spliceRoll}`);
  await say('스플라이스 롤의 이력입니다. 부모 롤 둘과 불합격 검사 결과가 한 화면에 있습니다.', `롤 이력 ${spliceRoll} — 부모 2 (splice) · 검사 불합격`);
  const hist = await h.bodyText();
  const spliceRows = await page.locator('table.grid tr', { hasText: 'splice' }).count();
  await box(page.locator('table.grid').nth(1), 2200);
  await check(`롤 이력 — splice 행 ${spliceRows} · 부모 ${slitRolls[1]}, ${slitRolls[2]} · 불합격`, spliceRows >= 2 && hist.includes(slitRolls[1]) && hist.includes(slitRolls[2]) && hist.includes('불합격'), String(spliceRows));

  // ── 4. Job-Lot-Roll 매핑 ──
  scene('4 · 매핑');
  await settle(0.2);
  await h.open(`/job/mapping?no=${jobNo}`);
  await say('작업지시 쪽에서 보면 잡 로트 롤 매핑입니다. 이 잡에서 나온 롤 다섯 개와 출하가 묶여 보입니다.', `Job-Lot-Roll 매핑 ${jobNo} — 롤 5 (인쇄 1 + 슬리팅 3 + splice 1) · 출하 1`);
  const rolls = sql1(`select count(*) from roll r join job j on j.job_id = r.job_id where j.job_no = '${jobNo}'`)?.[0];
  const mapText = await h.bodyText();
  await box(page.locator('table.grid').first(), 2000);
  await check(`Job ${jobNo} 의 롤 ${rolls}개 = 5 · 화면에 전부 표시`, rolls === '5' && [printRoll, ...slitRolls, spliceRoll].every((x) => mapText.includes(x)), rolls);

  // ── 5. 불량 집계 · 실적 현황 · 현황판 ──
  scene('5 · 집계');
  await settle(0.2);
  await h.open('/qua/defect-stats');
  await say('불량 유형별 집계입니다. 방금 등록한 색차가 들어가 있습니다. 집계 에스큐엘은 스탯츠 모듈 한 곳에만 있고 캐시 테이블은 없습니다.',
    '불량 유형별 집계 — EX-DF-01 색차 포함 · 집계 SQL 은 stats 한 곳 · 캐시 테이블 없음');
  const dfRow = page.locator('table.grid tr', { hasText: /EX-DF-01|색차/ }).first();
  await box(dfRow, 2000);
  await check('불량 집계에 색차(EX-DF-01) 행', (await dfRow.count()) === 1 && /[1-9]/.test(await dfRow.innerText()));
  await settle(0.2);
  await h.menu('/sta/summary');
  await say('실적 현황입니다. 생산, 품질, 납기 세 집계를 품목별로 봅니다.', '실적 현황 — 생산 · 품질 · 납기 집계');
  const sumTables = await page.locator('table.grid').count();
  await box(page.locator('table.grid').first(), 2000);
  await check(`실적 현황 표 ${sumTables}개 · 합계 행`, sumTables >= 1 && (await h.bodyText()).includes('합계'));
  await settle(0.2);
  await h.open('/sta/board?device=board');
  await say('같은 집계를 현황판 채널로 보면 메뉴 없이 큰 글씨로 오늘의 생산, 품질, 납기가 나오고 삼십 초마다 스스로 새로고침합니다. 오늘 값이 없는 칸은 지어내지 않고 미수집으로 적습니다.',
    '현황판 채널 — 메뉴 없음 · 큰 글씨 · 30초 자동 새로고침 · 값이 없는 칸은 「미수집」 (지어내지 않는다)');
  await page.locator('.tiles').waitFor();
  const tiles = await page.locator('.tiles .tile').count();
  const kpiVals = await page.locator('.kpi b').allInnerTexts();
  const filled = kpiVals.filter((v) => /^[\d.,%]+$/.test(v.trim())).length;
  const missing = kpiVals.filter((v) => v.includes('미수집')).length;
  await box(page.locator('.tiles'), 2400);
  await check(`현황판 — 타일 ${tiles} · 값 ${filled}칸 · 미수집 ${missing}칸 · 빈 칸 0 · board 채널`,
    tiles === 3 && kpiVals.length === filled + missing && kpiVals.length > 0 && /ch-board/.test(await page.locator('body').getAttribute('class')) && (await h.bodyText()).includes('자동 새로고침'),
    JSON.stringify(kpiVals));

  // ── 6. 보안 ──
  scene('6 · 보안');
  await settle(0.2);
  await say('이제 보안입니다. 중지된 계정은 퀵 로그인 패널에서 상태가 표시되고 단추가 막혀 있습니다. 요청을 직접 보내도 서버가 사백일로 거부하고 사유를 돌려줍니다.',
    '테스트 — 중지 계정 smp_prod_01: 단추 비활성 · 직접 POST → 401 「중지 상태 계정」 (의도한 동작)');
  await h.logout();
  const stoppedBtn = page.locator('button.quick-btn[value="smp_prod_01"]').first();
  if (!(await stoppedBtn.isVisible())) await r.click(stoppedBtn.locator('xpath=ancestor::details/summary'));
  await stoppedBtn.scrollIntoViewIfNeeded();
  await box(stoppedBtn, 2000);
  const stBadge = (await stoppedBtn.innerText()).replace(/\s+/g, ' ');
  const res401 = await h.postForm('/login/quick', { quick_id: 'smp_prod_01', device: 'web' });
  await check(`중지 계정 — 단추 비활성 「${stBadge}」 · 직접 POST → HTTP ${res401.status} 「${res401.body?.message ?? ''}」`,
    (await stoppedBtn.isDisabled()) && /중지/.test(stBadge) && res401.status === 401 && /중지/.test(res401.body?.message ?? ''), JSON.stringify(res401));
  await check('거부된 뒤에도 세션은 열리지 않았다', (await h.open('/')) === 401 || page.url().includes('/login'));
  await h.open('/login');
  await say('현장 계정으로 들어가 출하 승인을 시도합니다. 단추는 막혀 있고, 요청을 직접 보내도 서버가 사백삼으로 거부해 출하 상태는 그대로입니다.',
    '테스트 — 현장 계정: 승인 단추 비활성 · 직접 POST → 403 · 출하 상태 그대로 (의도한 동작)');
  await h.quickLogin('field');
  await h.open('/shp/approvals');
  // 목록은 한 쪽에 열 줄 — 지금 보이는 첫 승인 대기 행을 대상으로 한다
  const form = page.locator('tr:not([hidden]) form[action$="/approve"]').first();
  const target = (await form.getAttribute('action')).split('/')[3];
  const btn = form.locator('button').first();
  await btn.scrollIntoViewIfNeeded();
  await r.pause(300);
  await box(btn, 1500);
  const disabled = await btn.isDisabled();
  const code = await h.postStatus(`/shp/approvals/${target}/approve`);
  const still = sql1(`select status from shipment where shipment_no = '${target}'`)?.[0];
  await check(`현장 계정 승인 — 단추 비활성 · POST → HTTP ${code} · 출하 ${target} 상태 「${still}」`, disabled && code === 403 && still === '등록', `${disabled} ${code} ${still}`);
  const sysCode = await h.open('/sys/users');
  await box(page.locator('.login-card, .main, main').first(), 1800);
  await check(`현장 계정이 시스템 관리 주소를 열면 HTTP ${sysCode}`, sysCode === 403);

  // ── 7. 접근 로그 ──
  scene('7 · 접근 로그');
  await settle(0.2);
  await say('관리자로 돌아와 접근 로그를 봅니다. 방금 거부된 로그인 시도가 누가 언제, 어떤 사유로 막혔는지와 함께 남아 있습니다.',
    '접근 로그 — 구분 로그인 · 결과 실패 → 「로그인 실패: 중지 계정 · 퀵 로그인」');
  await h.logout();
  await h.quickLogin('admin');
  await h.open('/sys/logs?log_type=로그인&result=실패');
  const failRow = page.locator('table.grid tr', { hasText: 'smp_prod_01' }).first();
  await box(failRow, 2200);
  await check('로그: smp_prod_01 「로그인 실패: 중지 계정 · 퀵 로그인」', (await failRow.count()) === 1 && /중지/.test(await failRow.innerText()) && /퀵 로그인/.test(await failRow.innerText()));
  const okLogins = sql1(`select count(*) from sys_access_log where log_type = '로그인' and result = '성공' and detail like '%퀵 로그인%'`)?.[0];
  await check(`이번 시연의 퀵 로그인 성공 기록 ${okLogins}건 (전부 계정·시각과 함께)`, Number(okLogins) >= 5, okLogins);
  await settle(0.3);

  scene('결과');
  await r.resultCard('시연 4 · 추적 · 현황 · 보안 — 검증 결과');
  await say('네 편의 시연이 모두 끝났습니다. 출하 롤 하나에서 원재료 로트까지 추적되고, 권한과 상태는 요청마다 디비에서 확인됩니다. 감사합니다.',
    '출하 롤 하나 → 원재료 LOT 추적 완료 · 권한·상태는 요청마다 DB 에서 확인 · 시연 끝');
  await r.stop(1.5);
}
