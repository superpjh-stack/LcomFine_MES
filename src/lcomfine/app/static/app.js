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

  /* 스캔칸 — 화면이 열리면 포커스를 잡고, 다른 곳을 눌렀다가 놓아도 다시 잡는다 (G-13).
     입력칸·선택칸·버튼을 쓰는 동안에는 빼앗지 않는다. */
  var scan = document.querySelector("[data-scan]");
  function focusScan() {
    if (!scan || !layerHidden()) return;
    var a = document.activeElement;
    if (a && a !== document.body && a !== scan && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(a.tagName)) return;
    scan.focus();
  }
  function layerHidden() {
    var l = document.getElementById("popup-layer");
    return !l || l.hidden;
  }
  if (scan) {
    focusScan();
    document.addEventListener("click", function () { setTimeout(focusScan, 0); });
    window.addEventListener("focus", focusScan);
  }

  /* 알림 팝업 — 쓰기 결과·입력 검증 실패(422). 닫으면 스캔칸으로 돌아간다(다음 스캔을 막지 않는다) */
  var layer = document.getElementById("popup-layer");
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
    var ok = layer.querySelector("[data-popup-close]");
    if (ok) ok.focus();
  }
  function closePopup() { if (layer) { layer.hidden = true; focusScan(); } }
  if (layer) {
    layer.querySelectorAll("[data-popup-close]").forEach(function (b) { b.addEventListener("click", closePopup); });
    layer.addEventListener("click", function (e) { if (e.target === layer) closePopup(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !layer.hidden) closePopup(); });
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
})();
