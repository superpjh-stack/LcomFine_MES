// 시연 2 · 현장 POP — 없는 번호 스캔(422) → 입고 등록·라벨 → 입고검사(품질) → 작업 시작 → 자재 투입 → 조색 기록 → 정지·재개·폐기 → 작업 종료 → 롤 라벨
import { setupServer, helpers, loadState, saveState, MARK, sql1 } from './lib/mes.mjs';

export const config = { voice: 'Yuna', out: 'outputs/video/시연-02-현장POP.mp4' };
export const setup = setupServer;

export default async function scenario(r, env) {
  const { page, say, settle, scene, box, check } = r;
  const h = helpers(r, env);
  const st = loadState();
  const jobNo = st.jobNo ?? sql1(`select job_no from job where status = '등록' order by job_id desc limit 1`)?.[0];
  if (!jobNo) throw new Error('시연에 쓸 등록 상태 Job 이 없다 — 시연 1 을 먼저 돌린다');

  await r.goto('/login');
  await page.locator('.login-quick').waitFor();
  await r.card(`<h2>엘컴화인 MES · Job-Lot-Roll 계보</h2><h1>시연 2 · 현장 POP</h1>
    <h2>입고 → 입고검사 → 작업 시작 → 자재 투입 → 조색 → 정지·재개·폐기 → 작업 종료 → 롤 라벨</h2>
    <h2 style="font-size:19px;color:#93c5fd">스캔 = 바코드 스캐너의 키보드 입력 + Enter · 없는 번호를 스캔하는 장면도 넣었다</h2>`);
  await r.start();
  scene('시작');
  await say(`시연 두 번째, 현장 POP 편입니다. 현장 작업자가 작업지시 ${jobNo.replace(/(\\d)/g, '$1 ')} 를 받아 원재료 입고부터 인쇄 롤을 만들기까지를 스캔 위주로 진행합니다.`,
    `시연 2 · 현장 POP — Job ${jobNo} 를 받아 입고 → 투입 → 인쇄 롤 생성까지`);
  await settle(0.5);
  await r.card(null);

  // ── 1. 현장 계정 · POP 채널 ──
  scene('1 · 현장 로그인');
  await say('현장 작업자는 채널을 현장 POP 으로 고르고 퀵 로그인합니다. 채널은 글씨 크기와 배치만 바꾸고, 권한은 역할로 정해집니다.',
    '채널 「현장 POP」 선택 → 현장 작업자 (예시) field 퀵 로그인 · 채널은 레이아웃만, 권한은 역할');
  const code = await h.quickLogin('field', 'pop');
  const cls = await page.locator('body').getAttribute('class');
  await check('현장 퀵 로그인 → POP 채널 첫 화면(작업 실적)', code === 200 && /ch-pop/.test(cls) && page.url().includes('/pop/work'), `${code} ${cls} ${page.url()}`);
  await say('작업 실적 화면입니다. 스캔칸이 포커스를 쥐고 있어 스캐너가 쏘는 글자가 그대로 들어갑니다.',
    '작업 실적 — 스캔칸(data-scan)이 포커스를 가진다');
  await box(page.locator('[data-scan]'), 1800);

  // ── 2. 없는 번호 스캔 → 422 ──
  scene('2 · 없는 번호');
  await say('먼저 일부러 없는 번호를 스캔해 봅니다. 화면이 사라지지 않고, 사백이십이 상태로 같은 화면이 다시 그려지며 스캔칸이 남아 있어야 다음 스캔을 막지 않습니다.',
    '테스트 — 없는 번호 스캔: HTTP 422 로 같은 화면 다시 그림 · 스캔칸 유지 (의도한 동작)');
  const bad = await h.scan('VID-NOPE-0000');
  const err = page.locator('.err, [role=alert]').first();
  await box(err, 2000);
  const scanKept = await page.locator('[data-scan]').count();
  await check(`없는 번호 스캔 → HTTP ${bad} · 오류 문장 · 스캔칸 유지`, bad === 422 && scanKept === 1 && page.url().includes('/pop/work'), `${bad} scan=${scanKept}`);

  // ── 3. 입고 등록 ──
  scene('3 · 입고');
  await settle(0.2);
  await h.menu('/mat/receipts');
  await say('원재료 입고입니다. 품목, 공급처, 공급사 로트, 수량을 넣으면 원재료 LOT 번호가 채번되고 입고검사 대기 상태가 됩니다.',
    '입고 등록 — 원단 A (예시) · 2,000 m → 원재료 LOT 채번 · 입고검사 「대기」');
  const R = 'form#receipt-form';
  await h.selectByText(h.field(R, 'item_code'), 'EX-RM-01');
  await r.type(h.field(R, 'supplier_name'), `공급사 ${MARK}`);
  await r.type(h.field(R, 'supplier_lot_no'), 'SUP-261007-A');
  await r.type(h.field(R, 'received_qty'), '2000');
  await r.type(h.field(R, 'note'), `시연 ${MARK}`);
  await settle(0.2);
  await h.submit(R);
  const rmsg = await h.popupText();
  const lot = sql1(`select l.lot_no, l.insp_status from material_lot l join item i on i.item_id = l.item_id where i.item_code = 'EX-RM-01' and l.supplier_lot_no = 'SUP-261007-A' order by material_lot_id desc limit 1`);
  await check('입고 저장 알림', (await h.popupOpen()) && !(await h.popupWarn()), rmsg);
  await check(`원재료 LOT ${lot?.[0]} 채번 · 입고검사 ${lot?.[1]}`, !!lot && /^M\d{6}-\d{3}$/.test(lot[0]) && lot[1] === '대기', JSON.stringify(lot));
  const lotNo = lot[0];
  saveState({ lotNo });
  await h.closePopup();
  await say(`LOT ${lotNo.replace(/(\\d)/g, '$1 ')} 의 라벨입니다. 이 바코드를 투입 때 스캔합니다.`, `원재료 LOT 라벨 — ${lotNo} (Code128)`);
  await h.open(`/mat/lots/${lotNo}/label`);
  await box(page.locator('svg').first(), 1800);
  await check('원재료 LOT 라벨에 바코드 SVG', (await page.locator('svg').count()) >= 1 && (await h.bodyText()).includes(lotNo));

  // ── 4. 입고검사 — 현장은 못 하고 품질이 한다 ──
  scene('4 · 입고검사');
  await settle(0.2);
  await h.open(`/mat/inspections?no=${lotNo}`);
  await say('입고검사입니다. 현장 계정은 자재 입력 권한은 있지만 입고검사 범위는 없어서 합격, 불합격 단추가 막혀 있습니다. 권한 표의 괄호 조건 그대로입니다.',
    '현장 계정: 합격·불합격 단추 비활성 — 권한 표 「입력 (입고검사)」 는 품질만 (의도한 동작)');
  const passBtn = page.locator('button[form=insp-form][value=합격]');
  await box(passBtn, 2000);
  await check('현장 계정의 입고검사 단추 비활성', await passBtn.isDisabled());
  await say('품질 담당으로 바꿔 로그인해 같은 LOT 을 스캔하고 합격 처리합니다.', '로그아웃 → 품질 담당 (예시) qc 퀵 로그인 → LOT 스캔 → 합격');
  await h.logout();
  await h.quickLogin('qc');
  await h.open('/mat/inspections');
  await h.scan(lotNo);
  await r.type(h.field('form#insp-form', 'note'), `외관 이상 없음 ${MARK}`);
  await Promise.all([page.waitForNavigation(), r.click(page.locator('button[form=insp-form][value=합격]'))]);
  await r.pause(500);
  const imsg = await h.popupText();
  const ist = sql1(`select insp_status from material_lot where lot_no = '${lotNo}'`)?.[0];
  await check(`입고검사 합격 — LOT ${lotNo} 상태 ${ist}`, ist === '합격' && (await h.popupOpen()) && !(await h.popupWarn()), imsg);
  await h.closePopup();

  // ── 5. 작업 시작 ──
  scene('5 · 작업 시작');
  await say('다시 현장 작업자로 돌아와 작업지시서 바코드를 스캔합니다.', '현장 작업자 (예시) 로 다시 로그인 → 작업지시서 바코드 스캔');
  await h.logout();
  await h.quickLogin('field', 'pop');
  const sc = await h.scan(jobNo);
  await check(`Job ${jobNo} 스캔 → 작업 시작 폼`, sc === 200 && (await page.locator('form#start-form').count()) === 1, String(sc));
  await say('잡이 열리고 시작 폼이 나옵니다. 설비는 작업지시의 계획 설비를 그대로 씁니다. 시작하면 실적 한 줄이 진행 상태로 생깁니다.',
    '작업 시작 → work_result 한 줄 「진행」');
  await h.submit('form#start-form');
  const work = sql1(`select w.work_result_id, w.status from work_result w join job j on j.job_id = w.job_id where j.job_no = '${jobNo}' order by work_result_id desc limit 1`);
  await check(`작업 시작 — 실적 ${work?.[0]} 「${work?.[1]}」`, !!work && work[1] === '진행' && (await h.popupOpen()) && !(await h.popupWarn()), JSON.stringify(work));
  const workId = work[0];
  saveState({ workId });
  await h.closePopup();

  // ── 6. 자재 투입 ──
  scene('6 · 자재 투입');
  await say('자재 투입으로 갑니다. 합격한 원재료 LOT 라벨을 스캔하면 이 실적에 투입이 기록됩니다. 검사 대기나 불합격 LOT 은 받지 않습니다.',
    '자재 투입 — 합격 LOT 라벨 스캔 → material_input · 대기·불합격 LOT 은 422');
  const inputLink = page.locator(`a[href='/mat/inputs?work_id=${workId}']`).first();
  await Promise.all([page.waitForNavigation(), r.click(inputLink)]);
  await r.pause(400);
  const isc = await h.scan(lotNo);
  const inputs = sql1(`select count(*) from material_input mi join material_lot l on l.material_lot_id = mi.material_lot_id where mi.work_result_id = ${workId} and l.lot_no = '${lotNo}'`)?.[0];
  await check(`LOT ${lotNo} 투입 기록 1건`, inputs === '1' && isc === 200, `${isc} rows=${inputs}`);
  await box(page.locator('table.grid').first(), 1800);
  await h.closePopup();

  // ── 7. 조색 기록 ──
  scene('7 · 조색');
  await settle(0.2);
  await h.menu('/clr/records');
  await say('조색 기록입니다. 잡 번호를 스캔하고 색 이름과 측정한 엘 에이 비 값, 기준 잉크조성을 넣어 등록합니다.',
    '조색 기록 — Job 스캔 → 색 이름 · L·a·b · 기준 잉크조성 EX-INK-01');
  await h.scan(jobNo);
  const C = 'form#record-form';
  await r.type(h.field(C, 'color_name'), `청록 ${MARK}`);
  await r.type(h.field(C, 'color_l'), '54.2');
  await r.type(h.field(C, 'color_a'), '-32.1');
  await r.type(h.field(C, 'color_b'), '-8.4');
  await h.selectByText(h.field(C, 'ink_code'), 'EX-INK-01');
  await settle(0.2);
  await h.submit(C);
  const crow = sql1(`select color_record_id, color_name from color_record c join job j on j.job_id = c.job_id where j.job_no = '${jobNo}' order by color_record_id desc limit 1`);
  await check(`조색 기록 등록 — ${crow?.[1]}`, !!crow && (await h.popupOpen()) && !(await h.popupWarn()), JSON.stringify(crow));
  await h.closePopup();
  await say('이어서 배합비를 넣습니다. 성분과 비율을 적고 저장하면 합이 백인지 확인한 뒤 통째로 저장됩니다.', '배합비 — 청색 베이스 60 % · 백색 40 % → 합 100 확인 후 저장');
  const M = 'form#mix-form';
  await page.locator(M).waitFor();
  const comp = page.locator(`${M} input[name=component_name]`);
  const pct = page.locator(`${M} input[name=ratio_pct]`);
  await r.type(comp.nth(0), `청색 베이스 ${MARK}`);
  await r.type(pct.nth(0), '60');
  await r.type(comp.nth(1), `백색 ${MARK}`);
  await r.type(pct.nth(1), '40');
  await settle(0.2);
  await h.submit(M, '배합비 저장');
  const mix = sql1(`select count(*), coalesce(sum(ratio_pct),0) from color_record_mix where color_record_id = ${crow[0]}`);
  await check(`배합비 ${mix?.[0]}행 · 합 ${Number(mix?.[1])} %`, !!mix && mix[0] === '2' && Number(mix[1]) === 100 && !(await h.popupWarn()), JSON.stringify(mix) + ' ' + (await h.popupText()));
  await h.closePopup();
  await box(page.locator(M), 1800);

  // ── 8. 정지 · 재개 · 폐기 ──
  scene('8 · 정지·폐기');
  await settle(0.2);
  await h.open(`/pop/stops?work_id=${workId}`);
  await say('정지와 폐기입니다. 잉크 교체로 정지를 등록하고 바로 재개합니다. 정지 시간은 실적에 누적됩니다.', '정지 등록 「잉크 교체 (예시)」 → 재개');
  const S = 'form#stop-form';
  await r.type(h.field(S, 'stop_reason'), `잉크 교체 ${MARK}`);
  await h.submit(S, '정지 등록');
  const stop = sql1(`select s.work_stop_id, w.status from work_stop s join work_result w using (work_result_id) where s.work_result_id = ${workId} and s.resumed_at is null order by s.work_stop_id desc limit 1`);
  await check(`정지 등록 — 실적 상태 「${stop?.[1]}」 · 정지 중`, !!stop && stop[1] === '정지' && !(await h.popupWarn()), JSON.stringify(stop));
  await h.closePopup();
  const resume = page.locator(`form[action='/pop/stops/${stop[0]}/resume'] button`).first();
  await Promise.all([page.waitForNavigation(), r.click(resume)]);
  await r.pause(400);
  const stop2 = sql1(`select (s.resumed_at is not null), w.status from work_stop s join work_result w using (work_result_id) where s.work_stop_id = ${stop[0]}`);
  await check(`재개 — 재개 시각 기록 · 실적 상태 「${stop2?.[1]}」`, !!stop2 && stop2[0] === 't' && stop2[1] === '진행' && !(await h.popupWarn()), JSON.stringify(stop2));
  await h.closePopup();
  await say('폐기는 수량과 불량코드를 함께 적습니다. 핀홀로 오십 미터를 폐기합니다.', '폐기 등록 — 50 m · 불량코드 EX-DF-02 핀홀 (예시)');
  const K = 'form#scrap-form';
  await r.type(h.field(K, 'scrap_qty'), '50');
  await r.type(h.field(K, 'qty_unit'), 'm');
  await h.selectByText(h.field(K, 'defect_code'), 'EX-DF-02');
  await r.type(h.field(K, 'reason'), `초기 세팅 불량 ${MARK}`);
  await h.submit(K, '폐기 등록');
  const scrap = sql1(`select count(*), coalesce(sum(scrap_qty),0) from work_scrap where work_result_id = ${workId}`);
  await check(`폐기 ${scrap?.[0]}건 · ${Number(scrap?.[1])} m`, !!scrap && scrap[0] === '1' && Number(scrap[1]) === 50 && !(await h.popupWarn()), JSON.stringify(scrap));
  await h.closePopup();

  // ── 9. 작업 종료 → 인쇄 롤 ──
  scene('9 · 작업 종료');
  await settle(0.2);
  await h.open('/pop/work');
  await say('작업 실적으로 돌아와 종료합니다. 실적 수량, 길이, 폭을 넣으면 인쇄 롤 한 개와 계보의 투입 행이 한 트랜잭션으로 만들어집니다.',
    '작업 종료 — 1,500 m · 폭 600 mm → 인쇄 롤 1 + roll_genealogy 「투입」 (원재료 LOT → 롤)');
  const Fn = `form[action='/pop/work/${workId}/finish']`;
  await page.locator(Fn).scrollIntoViewIfNeeded();
  await r.type(h.field(Fn, 'output_qty'), '1500');
  await r.type(h.field(Fn, 'length_m'), '1500');
  await r.type(h.field(Fn, 'width_mm'), '600');
  await h.submit(Fn);
  const roll = sql1(`select roll_no from roll where work_result_id = ${workId}`);
  const gen = sql1(`select count(*) from roll_genealogy g join roll r on r.roll_id = g.child_roll_id join material_lot l on l.material_lot_id = g.parent_material_lot_id where r.work_result_id = ${workId} and l.lot_no = '${lotNo}' and g.relation = '투입'`)?.[0];
  await check(`인쇄 롤 ${roll?.[0]} 생성 · 계보 「투입」 ${gen}행 (LOT → 롤)`, !!roll && /^R\d{6}-\d+$/.test(roll[0]) && gen === '1' && !(await h.popupWarn()), JSON.stringify([roll, gen]));
  const printRoll = roll[0];
  saveState({ printRoll });
  await h.closePopup();
  await say(`인쇄 롤 ${printRoll.replace(/(\\d)/g, '$1 ')} 의 라벨입니다. 다음 공정은 이 라벨을 스캔합니다.`, `롤 라벨 — ${printRoll} · 다음 공정(슬리팅·후가공·검사·출하)은 이 바코드를 스캔`);
  const label = page.locator(`a[href='/pop/roll-labels/${printRoll}/print']`).first();
  await Promise.all([page.waitForNavigation(), r.click(label)]);
  await r.pause(600);
  await box(page.locator('svg').first(), 2000);
  await check('롤 라벨에 롤 번호와 바코드 SVG', (await page.locator('svg').count()) >= 1 && (await h.bodyText()).includes(printRoll));
  await settle(0.4);

  scene('결과');
  await r.resultCard('시연 2 · 현장 POP — 검증 결과');
  await say('현장 편의 검증은 모두 통과했습니다. 다음 편은 생산과 품질 계정으로 슬리팅, 스플라이스, 검사, 출하, 승인까지 이어집니다.',
    '검증 전부 통과 · 다음: 시연 3 생산·품질 (슬리팅 → splice → 검사 → 출하 → 승인 · COA)');
  await r.stop(1.2);
}
