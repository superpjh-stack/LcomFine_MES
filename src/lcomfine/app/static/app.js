/* 공통 UI 동작 — 템플릿에는 스크립트가 없다. 이 파일 하나가 한다(외부 라이브러리 0).
   테마(라이트/다크 · localStorage) · 좌측 메뉴 접기(좁은 화면) · 확인 대화(`data-confirm`) · 첫 입력 포커스 ·
   목록 정렬 · 쪽 넘김 · 스캔칸 포커스 · 알림 팝업(`#popup-layer[data-flash]`).
   실패를 조용히 삼키지 않는다(콘솔에 남긴다). <head> 에서 읽힌다 — 테마는 곧바로, 나머지는 문서가 다 읽힌 뒤. */
(function () {
  "use strict";
  var THEME_KEY = "lcomfine-theme";
  var root = document.documentElement;
  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  var saved = storedTheme();
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn); else fn();
  }

  ready(function () {
  /* 테마 토글 — 지금 보이는 테마의 반대로 고정한다 */
  document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var cur = root.getAttribute("data-theme") ||
        (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = cur === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { console.warn("테마 저장 실패", e); }
    });
  });

  /* 좌측 메뉴 접기 — 900px 아래에서만 단추가 보인다 */
  var menuBtn = document.querySelector("[data-menu-toggle]");
  if (menuBtn) {
    menuBtn.addEventListener("click", function () {
      var open = !document.body.classList.contains("menu-open");
      document.body.classList.toggle("menu-open", open);
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {   /* 메뉴 밖을 누르면 닫는다 */
      if (!document.body.classList.contains("menu-open")) return;
      if (e.target.closest("#side-menu") || e.target.closest("[data-menu-toggle]")) return;
      document.body.classList.remove("menu-open");
      menuBtn.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && document.body.classList.contains("menu-open")) {
        document.body.classList.remove("menu-open");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.focus();
      }
    });
  }

  /* 확인 대화 — `<button data-confirm="정말 삭제할까요?">` · `<form data-confirm=…>` */
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("button[data-confirm], a[data-confirm], input[data-confirm]") : null;
    if (el && !window.confirm(el.getAttribute("data-confirm"))) { e.preventDefault(); e.stopPropagation(); }
  }, true);
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault(); });
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

  /* 쓰기 결과 · 입력 검증 실패 알림 — 서버가 `#popup-layer` 의 data-flash 에 JSON 으로 싣는다 */
  if (layer && layer.dataset.flash) {
    try {
      var f = JSON.parse(layer.dataset.flash);
      var body = f.message || "";
      if (f.fields && f.fields.length) {
        body += "\n" + f.fields.map(function (x) { return "· " + (x.name || "입력") + ": " + (x.reason || ""); }).join("\n");
      }
      if (body) popup(f.title || "알림", body, f.kind);
    } catch (e) { console.warn("알림 파싱 실패", e); }
  }

  /* 첫 입력 포커스 — 스캔칸이 없고 다른 것이 포커스를 갖지 않았을 때 본문의 첫 입력칸 */
  if (!scan && (!document.activeElement || document.activeElement === document.body) && !popupOpen()) {
    var first = document.querySelector("main input:not([type=hidden]):not([disabled]), main select:not([disabled]), main textarea:not([disabled])");
    if (first) first.focus({ preventScroll: true });
  }
  });
})();
