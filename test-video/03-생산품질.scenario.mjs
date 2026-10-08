// 시연 3 · 생산·품질 — 슬리팅(1→3) → splice(2→1) → 검사(합격·불합격) → 출하 등록·롤 스캔(불합격 롤 422) → 승인(관리자) → COA
import { setupServer, helpers, loadState, saveState, MARK, sql, sql1 } from './lib/mes.mjs';

export const config = { voice: 'Yuna', out: 'outputs/video/시연-03-생산품질.mp4' };
export const setup = setupServer;

export default async function scenario(r, env) {
  const { page, say, settle, scene, box, check } = r;
  const h = helpers(r, env);
  const st = loadState();
  const { jobNo, printRoll, lotNo } = st;
  if (!jobNo || !printRoll) throw new Error('시연 2 의 인쇄 롤이 없다 — 시연 1·2 를 먼저 돌린다');
  const spoken = (no) => no.replace(/(\d)/g, '$1 ');

  await r.goto('/login');
  await page.locator('.login-quick').waitFor();
  await r.card(`<h2>엘컴화인 MES · Job-Lot-Roll 계보</h2><h1>시연 3 · 생산 · 품질</h1>
    <h2>슬리팅 1→3 → splice 2→1 → 검사(합격·불합격) → 출하 롤 스캔 → 승인 → COA</h2>
    <h2 style="font-size:19px;color:#93c5fd">롤이 나뉘고 합쳐져도 roll_genealogy 에는 부모 → 자식 한 줄씩만 남는다</h2>`);
  await r.start();
  scene('시작');
  await say(`시연 세 번째, 생산과 품질 편입니다. 앞에서 만든 인쇄 롤 ${spoken(printRoll)} 을 슬리팅으로 나누고, 둘을 다시 스플라이스로 합치고, 검사와 출하, 승인까지 갑니다.`,
    `시연 3 — 인쇄 롤 ${printRoll} → 슬리팅 → splice → 검사 → 출하 → 승인 · COA`);
  await settle(0.5);
  await r.card(null);

  // ── 1. 슬리팅 ──
  scene('1 · 슬리팅');
  await say('생산 담당으로 퀵 로그인해 슬리팅 화면에서 인쇄 롤 라벨을 스캔합니다.', '생산 담당 (예시) prod 퀵 로그인 → 슬리팅 → 인쇄 롤 스캔');
  await h.quickLogin('prod');
  await h.open('/rll/slitting');
  const s1 = await h.scan(printRoll);
  await check(`인쇄 롤 ${printRoll} 스캔 → 슬리팅 폼`, s1 === 200 && (await page.locator('form#slit-form').count()) === 1, String(s1));
  await say('세 개로 나눕니다. 폭을 이백씩 적으면 자식 롤 세 개가 생기고, 계보에는 부모에서 자식으로 한 줄씩 세 줄이 남습니다. 부모 롤은 소진으로 바뀝니다.',
    '분할 3 · 폭 200,200,200 → 자식 롤 3 · 계보 「슬리팅」 3행 · 부모 롤 소진');
  const SL = 'form#slit-form';
  await r.type(h.field(SL, 'count'), '3');
  await r.type(h.field(SL, 'widths_mm'), '200,200,200');
  await h.selectByText(h.field(SL, 'equipment_code'), 'EX-EQ-03');
  await settle(0.2);
  await h.submit(SL);
  const slits = sql(`select c.roll_no from roll_genealogy g join roll c on c.roll_id = g.child_roll_id join roll p on p.roll_id = g.parent_roll_id
                     where p.roll_no = '${printRoll}' and g.relation = '슬리팅' order by c.roll_id`).map((x) => x[0]);
  await check(`슬리팅 롤 ${slits.length}개 · 계보 「슬리팅」 ${slits.length}행`, slits.length === 3 && !(await h.popupWarn()), slits.join(' ') + ' ' + (await h.popupText()));
  saveState({ slitRolls: slits });
  await h.closePopup();
  const made = page.locator('#made');
  await box(made, 2200);
  const sheets = await made.locator('.label-sheet svg').count();
  await check(`라벨 ${sheets}장이 바로 나온다 (인라인 SVG 바코드)`, sheets >= 3 && /3장/.test(await made.locator('h2').innerText()), String(sheets));

  // ── 2. splice ──
  scene('2 · splice');
  await settle(0.2);
  await h.menu('/rll/finishing');
  await say('후가공입니다. 슬리팅 롤 두 개를 차례로 스캔해 모은 뒤 하나로 잇습니다. 스플라이스는 부모 둘에서 자식 하나, 계보에는 두 줄이 남습니다.',
    `splice — ${slits[1]} + ${slits[2]} 스캔 → 후가공 롤 1 · 계보 「splice」 2행`);
  await h.scan(slits[1]);
  await h.scan(slits[2]);
  const FF = 'form#finish-form';
  const action = await page.locator(FF).getAttribute('action');
  await check('롤 2개가 모이면 폼이 splice 로 바뀐다', /\/splice$/.test(action || ''), String(action));
  await h.selectByText(h.field(FF, 'equipment_code'), 'EX-EQ-02');
  await r.type(h.field(FF, 'length_m'), '2800');
  await r.type(h.field(FF, 'width_mm'), '200');
  await settle(0.2);
  await h.submit(FF);
  const sp = sql(`select c.roll_no, p.roll_no from roll_genealogy g join roll c on c.roll_id = g.child_roll_id join roll p on p.roll_id = g.parent_roll_id
                  where g.relation = 'splice' and p.roll_no in ('${slits[1]}','${slits[2]}') order by p.roll_id`);
  const spliceRoll = sp[0]?.[0];
  await check(`splice 롤 ${spliceRoll} · 부모 ${sp.length}개 (${sp.map((x) => x[1]).join(', ')})`, sp.length === 2 && sp.every((x) => x[0] === spliceRoll) && !(await h.popupWarn()), JSON.stringify(sp) + ' ' + (await h.popupText()));
  saveState({ spliceRoll });
  await h.closePopup();

  // ── 3. 검사 ──
  scene('3 · 품질 검사');
  await say('품질 담당으로 바꿉니다. 슬리팅 롤 첫 번째는 델타 이 영점팔로 합격, 스플라이스 롤은 색차가 커서 불합격으로 등록합니다.',
    `품질 담당 (예시) qc → ${slits[0]} ΔE 0.8 합격 · ${spliceRoll} ΔE 3.2 불합격(색차 · 우측)`);
  await h.logout();
  await h.quickLogin('qc');
  await h.open('/qua/inspections');
  await h.scan(slits[0]);
  const Q = 'form#inspection-form';
  await r.type(h.field(Q, 'delta_e'), '0.8');
  await h.selectByText(h.field(Q, 'result'), '합격');
  await r.type(h.field(Q, 'note'), `시연 ${MARK}`);
  await h.submit(Q);
  const i1 = sql1(`select i.result from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = '${slits[0]}' order by inspection_id desc limit 1`)?.[0];
  await check(`${slits[0]} 검사 「${i1}」`, i1 === '합격' && !(await h.popupWarn()), await h.popupText());
  await say('알림이 떠 있어도 다음 스캔은 그대로 받습니다. 글자가 들어오면 알림이 닫히고 스캔칸에 이어집니다.', '알림 중 스캔 — 알림이 닫히고 다음 스캔이 이어진다');
  await h.scan(spliceRoll);
  await r.type(h.field(Q, 'delta_e'), '3.2');
  await h.selectByText(h.field(Q, 'result'), '불합격');
  await h.selectByText(page.locator(`${Q} select[name=defect_code]`).first(), 'EX-DF-01');
  await r.type(page.locator(`${Q} input[name=position]`).first(), `우측 20mm ${MARK}`);
  await r.type(h.field(Q, 'note'), `색차 초과 ${MARK}`);
  await h.submit(Q);
  const i2 = sql1(`select i.result, (select count(*) from inspection_defect d where d.inspection_id = i.inspection_id) from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = '${spliceRoll}' order by inspection_id desc limit 1`);
  await check(`${spliceRoll} 검사 「${i2?.[0]}」 · 불량 유형 ${i2?.[1]}건`, !!i2 && i2[0] === '불합격' && i2[1] === '1' && !(await h.popupWarn()), JSON.stringify(i2) + ' ' + (await h.popupText()));
  await h.closePopup();
  await box(page.locator('table.grid').first(), 1800);

  // ── 4. 출하 등록 · 롤 스캔 ──
  scene('4 · 출하');
  await settle(0.2);
  await say('생산 담당으로 돌아와 출하를 등록합니다. 출하 로트 하나에는 한 잡의 롤만 담습니다.', `생산 담당 → 출하 등록 (Job ${jobNo}) → 출하 LOT 채번`);
  await h.logout();
  await h.quickLogin('prod');
  await h.open('/shp/shipments');
  const SH = 'form#shipment-form';
  await r.type(h.field(SH, 'job_no'), jobNo);
  await r.type(h.field(SH, 'note'), `시연 ${MARK}`);
  await h.submit(SH);
  const ship = sql1(`select s.shipment_no, s.status from shipment s join job j on j.job_id = s.job_id where j.job_no = '${jobNo}' order by shipment_id desc limit 1`);
  await check(`출하 LOT ${ship?.[0]} 등록 「${ship?.[1]}」`, !!ship && ship[1] === '등록' && !(await h.popupWarn()), JSON.stringify(ship) + ' ' + (await h.popupText()));
  const shipNo = ship[0];
  saveState({ shipNo });
  await h.closePopup();
  await say('합격 롤을 스캔해 담습니다. 계보에는 롤에서 출하 로트로 출하 한 줄이 생깁니다.', `${slits[0]} 스캔 → 계보 「출하」 (롤 → 출하 LOT)`);
  const ok = await h.scan(slits[0]);
  const g1 = sql1(`select count(*) from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id join shipment s on s.shipment_id = g.child_shipment_id where r.roll_no = '${slits[0]}' and s.shipment_no = '${shipNo}'`)?.[0];
  await check(`${slits[0]} 담김 — 계보 「출하」 ${g1}행`, ok === 200 && g1 === '1', `${ok} ${g1}`);
  await say('이번에는 불합격 롤을 스캔합니다. 서버가 막고 사유를 알림으로 보여 주며, 출하에는 담기지 않아야 합니다. 의도한 동작입니다.',
    `테스트 — 불합격 롤 ${spliceRoll} 스캔 → 거부 · 사유 알림 · 출하에 담기지 않는다 (의도한 동작)`);
  await h.scan(spliceRoll);
  const g2 = sql1(`select count(*) from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id join shipment s on s.shipment_id = g.child_shipment_id where r.roll_no = '${spliceRoll}' and s.shipment_no = '${shipNo}'`)?.[0];
  const warn = await h.popupWarn();
  const why = await h.popupText();
  await box(h.popup().locator('.popup'), 2400);
  await check(`불합격 롤 스캔 거부 — 사유 「${why.split('\n')[0]}」 · 담기지 않음(${g2}행)`, warn && g2 === '0' && /불합격/.test(why), `${warn} ${g2} ${why.slice(0, 80)}`);
  await h.closePopup();
  const cnt = sql1(`select count(*) from roll_genealogy g join shipment s on s.shipment_id = g.child_shipment_id where s.shipment_no = '${shipNo}'`)?.[0];
  await check(`출하 LOT ${shipNo} 에 담긴 롤 ${cnt}개`, cnt === '1');

  // ── 5. 승인 · COA ──
  scene('5 · 승인 · COA');
  await settle(0.2);
  await say('출하 승인은 관리자만 합니다. 관리자로 로그인해 승인하면 씨오에이 번호가 채번되고 그 뒤에는 바꿀 수 없습니다.',
    '관리자 (예시) admin → 출하 승인 → COA 번호 채번 · 이후 변경 불가');
  await h.logout();
  await h.quickLogin('admin');
  await h.open('/shp/approvals');
  const ap = page.locator(`form[action='/shp/approvals/${shipNo}/approve'] button`).first();
  await ap.scrollIntoViewIfNeeded();   // 표가 패널보다 넓다 — 가로로 밀어 승인 단추를 보이게 한다
  await r.pause(400);
  await box(ap, 1200);
  await h.clickNav(ap);
  await h.popup().waitFor({ state: 'visible' });
  const sh2 = sql1(`select status, coa_no from shipment where shipment_no = '${shipNo}'`);
  await check(`승인 — 상태 「${sh2?.[0]}」 · COA ${sh2?.[1]}`, !!sh2 && sh2[0] === '승인' && !!sh2[1] && !(await h.popupWarn()), JSON.stringify(sh2) + ' ' + (await h.popupText()));
  saveState({ coaNo: sh2[1] });
  await h.closePopup();
  await say('씨오에이입니다. 담긴 롤과 검사값이 그대로 들어갑니다. 불합격 롤은 담기지 않았으니 여기에도 없습니다.', `COA ${sh2[1]} — 담긴 롤 ${slits[0]} · ΔE 0.8 · 합격`);
  await h.menu('/shp/coa');
  const coaLink = page.locator(`a[href='/shp/coa/${shipNo}/print']`).first();
  await coaLink.scrollIntoViewIfNeeded();   // 표가 넓으면 가로로 밀어 보이게
  await r.pause(300);
  await coaLink.evaluate((a) => a.removeAttribute('target'));
  await h.clickNav(coaLink);
  await page.locator('table').first().waitFor();
  await r.pause(400);
  const coaText = await h.bodyText();
  await box(page.locator('table').first(), 2200);
  await check(`COA 에 롤 ${slits[0]} · ΔE 0.8 · 합격, 불합격 롤 없음`, coaText.includes(slits[0]) && /0\.8/.test(coaText) && coaText.includes('합격') && !coaText.includes(spliceRoll), coaText.slice(0, 120));
  await settle(0.4);

  scene('결과');
  await r.resultCard('시연 3 · 생산 · 품질 — 검증 결과');
  await say('생산 품질 편의 검증은 모두 통과했습니다. 마지막 편은 출하 로트에서 원재료 로트까지 추적하고, 현황과 보안을 확인합니다.',
    '검증 전부 통과 · 다음: 시연 4 추적 · 현황 · 보안');
  await r.stop(1.2);
}
