/* 공통 UI 동작 — 좌측 메뉴 접기 · 목록 정렬·쪽 넘김 · 알림 팝업 · 스캔칸 포커스.
   외부 라이브러리 0. 실패를 조용히 삼키지 않는다(콘솔에 그대로 남긴다). */
(function () {
  "use strict";

  /* 좌측 메뉴 접기/펼치기 */
  document.querySelectorAll(".menu-head").forEach(function (head) {
    head.addEventListener("click", function () {
      head.parentElement.classList.toggle("open");
    });
  });

  /* 목록 머리행 클릭 정렬 */
  function dataRows(table) {
    return Array.prototype.slice.call(table.tBodies[0] ? table.tBodies[0].rows : []).filter(function (r) {
      return !r.querySelector(".empty");
    });
  }
  document.querySelectorAll("table.grid:not(.plain) thead th").forEach(function (th) {
    th.addEventListener("click", function () {
      var table = th.closest("table"), tbody = table.tBodies[0];
      if (!tbody) return;
      var idx = Array.prototype.indexOf.call(th.parentElement.cells, th);
      var asc = th.dataset.sort !== "asc";
      table.querySelectorAll("thead th").forEach(function (o) { delete o.dataset.sort; });
      th.dataset.sort = asc ? "asc" : "desc";
      var rows = dataRows(table);
      rows.sort(function (a, b) {
        var x = (a.cells[idx] ? a.cells[idx].textContent : "").trim();
        var y = (b.cells[idx] ? b.cells[idx].textContent : "").trim();
        var nx = parseFloat(x.replace(/[, ]/g, "")), ny = parseFloat(y.replace(/[, ]/g, ""));
        var cmp = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : x.localeCompare(y, "ko");
        return asc ? cmp : -cmp;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
      table.dataset.page = "1";
      applyPage(table);
    });
  });

  /* 목록 쪽 넘김 — 서버는 상한만 걸고 화면이 한 쪽씩 보인다 */
  var PAGE = parseInt(document.body.dataset.gridPageSize || "10", 10) || 10;
  function applyPage(table) {
    var rows = dataRows(table), total = rows.length;
    var pages = Math.max(1, Math.ceil(total / PAGE));
    var cur = Math.min(Math.max(1, parseInt(table.dataset.page || "1", 10) || 1), pages);
    table.dataset.page = String(cur);
    rows.forEach(function (r, i) { r.hidden = (i < (cur - 1) * PAGE || i >= cur * PAGE); });
    var bar = table.nextElementSibling;
    if (!bar || !bar.classList.contains("pager")) {
      bar = document.createElement("div"); bar.className = "pager";
      table.parentNode.insertBefore(bar, table.nextSibling);
      bar.innerHTML = '<button type="button" class="btn btn-sm" data-pg="prev">이전</button>' +
        '<span class="pg-info"></span>' +
        '<button type="button" class="btn btn-sm" data-pg="next">다음</button>';
    }
    bar.hidden = total <= PAGE;
    bar.querySelector(".pg-info").textContent = total ? (cur + " / " + pages + " 쪽 · " + total + "행") : "";
    bar.querySelector('[data-pg="prev"]').disabled = cur <= 1;
    bar.querySelector('[data-pg="next"]').disabled = cur >= pages;
    bar.querySelector('[data-pg="prev"]').onclick = function () { table.dataset.page = String(cur - 1); applyPage(table); };
    bar.querySelector('[data-pg="next"]').onclick = function () { table.dataset.page = String(cur + 1); applyPage(table); };
  }
  document.querySelectorAll("table.grid:not(.plain)").forEach(function (t) { applyPage(t); });

  /* 스캔칸 · 알림 팝업 (G-13 · D-04: 스캐너 = 키보드 입력 + Enter)
     스캔칸(`[data-scan]`)이 있는 화면에서는 **스캔칸이 포커스의 주인**이다:
       · 화면이 열리면 포커스를 잡고, 빈 곳을 눌렀다 놓아도 다시 잡는다. 다른 입력칸·선택칸·버튼을 쓰는 동안에는 빼앗지 않는다.
       · 알림이 떠도 포커스를 「확인」 버튼에 주지 않는다 — 알림이 떠 있는 채로 쏜 바코드의 글자가 스캔칸에 들어가고 Enter 가 그 스캔을 보낸다
         (버려지지 않는다). 첫 글자가 오면 알림은 닫힌다.
       · 알림을 「확인」·바깥 누르기·Esc·(빈 스캔칸에서) Enter 로 닫으면 포커스가 스캔칸으로 돌아온다.
     템플릿이 따로 할 일은 없다. 스캔칸이 없는 화면의 알림은 「확인」 버튼이 포커스를 가진다(Enter 로 닫힌다). */
  var scan = document.querySelector("[data-scan]");
  var layer = document.getElementById("popup-layer");
  function popupOpen() { return !!layer && !layer.hidden; }
  function idle(a) {   /* 포커스가 아무 데도 없거나(본문) 알림 안(「확인」)에 있다 = 사용자가 다른 칸을 쓰고 있지 않다 */
    return !a || a === document.body || a === scan || (!!layer && layer.contains(a)) || !/^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(a.tagName);
  }
  function focusScan() {
    if (scan && document.activeElement !== scan && idle(document.activeElement)) scan.focus();
  }
  if (scan) {
    focusScan();
    document.addEventListener("click", function () { setTimeout(focusScan, 0); });
    window.addEventListener("focus", focusScan);
  }

  /* 알림 팝업 — 쓰기 결과·입력 검증 실패(422). 다음 스캔을 막지 않는다 */
  function popup(title, body, kind) {
    if (!layer) { console.warn("popup layer 없음:", title, body); return; }
    layer.querySelector(".popup").classList.toggle("warn", kind === "warn");
    document.getElementById("popup-title").textContent = title || "알림";
    var box = document.getElementById("popup-body");
    box.innerHTML = "";
    var p = document.createElement("p");
    p.textContent = body || "";
    box.appendChild(p);
    layer.hidden = false;
    if (scan) { focusScan(); return; }
    var ok = layer.querySelector("[data-popup-close]");
    if (ok) ok.focus();
  }
  function closePopup() {
    if (!layer) return;
    layer.hidden = true;
    focusScan();   /* 방금 누른 「확인」 이 아직 포커스를 쥐고 있어도 스캔칸으로 돌려준다 */
  }
  if (layer) {
    layer.querySelectorAll("[data-popup-close]").forEach(function (b) { b.addEventListener("click", closePopup); });
    layer.addEventListener("click", function (e) { if (e.target === layer) closePopup(); });
    document.addEventListener("keydown", function (e) {
      if (!popupOpen()) return;
      if (e.key === "Escape") { closePopup(); return; }
      if (!scan) return;
      var a = document.activeElement;
      if (e.key === "Enter") {
        /* 스캔칸에 글자가 있으면 그 스캔을 보낸다(브라우저 기본 동작). 스캔칸이 비었거나 포커스가 없으면 알림만 닫는다.
           「확인」 버튼의 Enter 는 클릭이고, 다른 입력칸의 Enter 는 그 폼의 것이다 — 건드리지 않는다 */
        if ((a === scan && scan.value === "") || !a || a === document.body) { e.preventDefault(); closePopup(); }
        return;
      }
      if (e.key && e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.altKey && idle(a)) {
        closePopup();   /* 글자 키 = 다음 스캔의 시작. 알림을 닫고 포커스를 스캔칸에 두면 이 글자가 그대로 들어간다 */
      }
    }, true);
  }
  window.lcomfinePopup = popup;

  var flashEl = document.getElementById("flash-data");
  if (flashEl) {
    try {
      var f = JSON.parse(flashEl.textContent || "{}");
      var body = f.message || "";
      if (f.fields && f.fields.length) {
        body += "\n" + f.fields.map(function (x) { return "· " + (x.name || "입력") + ": " + (x.reason || ""); }).join("\n");
      }
      if (body) popup(f.title || "알림", body, f.kind);
    } catch (e) { console.warn("flash 파싱 실패", e); }
  }

  /* 현황판 자동 새로고침 (G-13 · D-27) — 조작 없이 다시 그린다. 오류 화면(_error.html)에서도 같은 코드가 돈다.
     meta refresh 만 쓰면 서버가 잠깐 내려간 사이에 브라우저의 오류 화면으로 넘어가 거기서 멈춘다. 그래서 주기마다 먼저
     서버가 응답하는지(/health — 상태코드는 따지지 않는다) 보고, 응답이 오면 이 주소를 다시 그리고, 안 오면 화면에 남아
     「연결 끊김」 을 띄운 채 다시 시도한다. 낡은 화면을 새것처럼 보이게 두지 않는다. */
  var refreshSeconds = parseInt(document.body.dataset.refreshSeconds || "0", 10) || 0;
  var RETRY_MS = 5000;
  function showStale() {
    var bar = document.getElementById("stale-banner");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "stale-banner"; bar.className = "stale-banner"; bar.setAttribute("role", "alert");
      document.body.appendChild(bar);
    }
    var at = document.getElementById("refreshed-at");
    bar.textContent = "서버 연결 끊김 — 다시 시도하는 중" + (at ? " (화면은 " + at.textContent + " 기준)" : "");
  }
  function refreshTick() {
    if (!window.fetch) { location.reload(); return; }
    fetch("/health", { cache: "no-store", credentials: "same-origin" })
      .then(function () { location.reload(); })
      .catch(function (err) {
        console.warn("현황판 새로고침 실패 — 서버 응답 없음", err);
        showStale();
        setTimeout(refreshTick, RETRY_MS);
      });
  }
  if (refreshSeconds > 0) setTimeout(refreshTick, refreshSeconds * 1000);
})();
