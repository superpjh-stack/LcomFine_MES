/* 공통 UI 동작 — 템플릿에는 스크립트가 없다. 이 파일 하나가 한다(외부 라이브러리 0).
   테마(라이트/다크 · localStorage) · 좌측 메뉴 슬라이드·하위 메뉴 접기 · 확인 대화(`data-confirm`) · 첫 입력 포커스 ·
   목록 정렬 · 쪽 넘김 · 수주 진행보드 자동 갱신 · 스캔칸 포커스 · 알림 팝업(`#popup-layer[data-flash]`).
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

  /* 슬라이드 메뉴: 데스크톱은 본문 폭을 확장하고 모바일은 오버레이로 연다. */
  var menuBtn = document.querySelector("[data-menu-toggle]");
  var side = document.getElementById("side-menu");
  var narrow = window.matchMedia("(max-width: 900px)");
  if (menuBtn && side) {
    function setMenu(open, restoreFocus) {
      document.body.classList.toggle("menu-open", open);
      document.body.classList.toggle("menu-collapsed", !open);
      menuBtn.setAttribute("aria-expanded", String(open));
      side.inert = !open;
      if (restoreFocus) menuBtn.focus();
    }
    setMenu(!narrow.matches);
    narrow.addEventListener("change", function () { setMenu(!narrow.matches); });
    menuBtn.addEventListener("click", function () {
      var open = menuBtn.getAttribute("aria-expanded") !== "true";
      setMenu(open);
      if (open && narrow.matches) side.querySelector("[data-menu-close]").focus();
    });
    side.querySelector("[data-menu-close]").addEventListener("click", function () { setMenu(false, true); });
    document.addEventListener("click", function (e) {
      if (narrow.matches && document.body.classList.contains("menu-open") &&
          !side.contains(e.target) && !menuBtn.contains(e.target)) setMenu(false);
    });
    document.addEventListener("keydown", function (e) {
      if (!document.body.classList.contains("menu-open")) return;
      if (e.key === "Escape") { setMenu(false, true); return; }
      if (e.key === "Tab" && narrow.matches) {
        var items = Array.from(side.querySelectorAll('button, a[href]')).filter(function (el) {
          return !el.closest('[inert]') && el.getClientRects().length;
        });
        var first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
  }
  document.querySelectorAll("[data-submenu-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      button.closest(".side__menu").classList.toggle("is-open", open);
      document.getElementById(button.getAttribute("aria-controls")).inert = !open;
    });
  });

  /* 접힌 폼 열기 — 「＋ 등록」 처럼 `#id` 로 가는 링크가 접힌 <details> 안을 가리키면 그 <details> 를 연다(주소의 #id 로 열린 화면도) */
  function openTarget(hash) {
    if (!hash || hash.length < 2) return;
    var el = null;
    try { el = document.getElementById(decodeURIComponent(hash.slice(1))); } catch (e) { console.warn("앵커 해석 실패", e); return; }
    for (var d = el; d; d = d.parentElement) { if (d.tagName === "DETAILS") d.open = true; }
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  openTarget(location.hash);
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (a) openTarget(a.getAttribute("href"));
  });

  /* 자동 제출 — `<form data-auto-submit>` 은 화면이 열리면 한 번 제출한다(문서관리 SSO 진입 · D-514 · F-DOC-011).
     토큰은 hidden 칸에만 있고 POST 로 넘어가 주소창에 남지 않는다. 막히면 사람이 단추를 누르면 된다(단추는 그대로 보인다). */
  document.querySelectorAll("form[data-auto-submit]").forEach(function (f) {
    if (f.getAttribute("data-auto-submitted")) return;
    f.setAttribute("data-auto-submitted", "1");
    try { f.submit(); } catch (e) { console.warn("자동 제출 실패 — 단추를 눌러 주세요", e); }
  });

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
      if (!table.closest(".data-table")) applyPage(table);
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
  /* 대시보드의 접힌 데이터 표(`details.data-table`)는 쪽 넘김 없이 표 전체 — 차트와 같은 숫자를 한눈에 */
  document.querySelectorAll("table.grid:not(.plain)").forEach(function (t) { if (!t.closest(".data-table")) applyPage(t); });

  /* 홈 수주 진행보드 — 전체 페이지를 흔들지 않고 보드 조각만 30초마다 갱신한다.
     탭이 백그라운드일 때는 요청을 멈추고, 다시 돌아오면 즉시 한 번 확인한다. */
  (function initOrderProgressRefresh() {
    var board = document.querySelector("[data-order-progress]");
    if (!board || !window.fetch || !window.DOMParser) return;
    var seconds = Math.max(10, parseInt(board.getAttribute("data-progress-refresh") || "30", 10) || 30);
    var timer = null, busy = false, live = board.querySelector("[data-progress-live]");
    function clock() {
      try { return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
      catch (e) { return "방금"; }
    }
    function setLive(text, state) {
      if (!live) return;
      live.textContent = text;
      live.classList.toggle("is-refreshing", state === "refreshing");
      live.classList.toggle("is-error", state === "error");
    }
    function schedule() {
      window.clearTimeout(timer);
      if (document.hidden) return;
      timer = window.setTimeout(function () {
        refresh().then(schedule);
      }, seconds * 1000);
    }
    function refresh() {
      if (busy || document.hidden) return Promise.resolve();
      busy = true;
      setLive("갱신 중…", "refreshing");
      return fetch(window.location.href, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "text/html", "X-Requested-With": "progress-refresh" }
      }).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      }).then(function (html) {
        var parsed = new DOMParser().parseFromString(html, "text/html");
        var next = parsed.querySelector("[data-order-progress]");
        if (!next) throw new Error("진행보드 응답이 없습니다");
        board.replaceWith(next);
        board = next;
        live = board.querySelector("[data-progress-live]");
        setLive("자동 갱신 " + seconds + "초 · " + clock(), "ok");
      }).catch(function (error) {
        console.warn("수주 진행보드 자동 갱신 실패", error);
        setLive("갱신 실패 · " + seconds + "초 후 재시도", "error");
      }).then(function () { busy = false; });
    }
    setLive("자동 갱신 " + seconds + "초 · " + clock(), "ok");
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) { refresh().then(schedule); }
      else window.clearTimeout(timer);
    });
    schedule();
  }());

  /* 스캔칸 · 알림 팝업 (G-13 · D-04: 스캐너 = 키보드 입력 + Enter)
     스캔칸(`[data-scan]`)이 있는 화면에서는 **스캔칸이 포커스의 주인**이다:
       · 화면이 열리면 포커스를 잡고, 빈 곳을 눌렀다 놓아도 다시 잡는다. 다른 입력칸·선택칸·버튼을 쓰는 동안에는 빼앗지 않는다.
       · 알림이 떠도 포커스를 「확인」 버튼에 주지 않는다 — 알림이 떠 있는 채로 쏜 바코드의 글자가 스캔칸에 들어가고 Enter 가 그 스캔을 보낸다
         (버려지지 않는다). 첫 글자가 오면 알림은 닫힌다.
       · 알림을 「확인」·바깥 누르기·Esc·(빈 스캔칸에서) Enter 로 닫으면 포커스가 스캔칸으로 돌아온다.
     템플릿이 따로 할 일은 없다. 스캔칸이 없는 화면의 알림은 「확인」 버튼이 포커스를 가진다(Enter 로 닫힌다). */
  var scan = document.querySelector("[data-scan]");
  var layer = document.getElementById("popup-layer");
  var cmdLayer = document.getElementById("cmd-palette");
  function popupOpen() { return (!!layer && !layer.hidden) || (!!cmdLayer && !cmdLayer.hidden); }
  function idle(a) {   /* 포커스가 아무 데도 없거나(본문) 알림 안(「확인」)에 있다 = 사용자가 다른 칸을 쓰고 있지 않다 */
    if (cmdLayer && !cmdLayer.hidden) return false;
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

  /* 현장 스캔 파일럿 — BarcodeDetector가 있는 브라우저에서만 카메라를 연다.
     인식 결과는 기존 검색 폼으로만 넘기며, 저장·재고 변경은 하지 않는다. */
  document.querySelectorAll("[data-camera-open]").forEach(function (open) {
    var form = open.closest("[data-barcode-form]");
    if (!form) return;
    var panel = form.querySelector("[data-camera-panel]");
    var video = form.querySelector("[data-camera-video]");
    var status = form.querySelector("[data-camera-status]");
    var input = form.querySelector("[data-barcode-input]");
    var stream = null;
    var running = false;
    function message(text) { if (status) status.textContent = text; }
    function stop() {
      running = false;
      if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
      stream = null;
      if (video) video.srcObject = null;
      if (panel) panel.hidden = true;
    }
    form.querySelectorAll("[data-camera-close]").forEach(function (close) { close.addEventListener("click", stop); });
    open.addEventListener("click", function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.BarcodeDetector) {
        if (panel) panel.hidden = false;
        message("이 브라우저는 카메라 스캔을 지원하지 않습니다. 상단 입력창에 직접 입력해 주세요.");
        return;
      }
      if (panel) panel.hidden = false;
      message("카메라 권한을 확인하고 있습니다.");
      navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
        .then(function (got) {
          stream = got;
          video.srcObject = stream;
          return video.play();
        })
        .then(function () {
          var detector = new BarcodeDetector({ formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8"] });
          running = true;
          message("코드를 화면 안에 맞춰 주세요.");
          function scanFrame() {
            if (!running) return;
            detector.detect(video).then(function (codes) {
              if (codes && codes.length && codes[0].rawValue) {
                input.value = codes[0].rawValue;
                stop();
                if (form.requestSubmit) form.requestSubmit(); else form.submit();
                return;
              }
              window.requestAnimationFrame(scanFrame);
            }).catch(function () { window.requestAnimationFrame(scanFrame); });
          }
          scanFrame();
        })
        .catch(function () { message("카메라를 열 수 없습니다. 권한을 허용하거나 상단 입력창을 사용해 주세요."); stop(); });
    });
  });

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

  /* 빠른 화면 이동 (Command Palette · Ctrl+K / ⌘K) — 현재 사용자의 좌측 메뉴(#side-menu)와 상단 주 메뉴에서 항목을 읽어 즉시 검색·이동 */
  if (cmdLayer) {
    var cmdInput = document.getElementById("cmd-input");
    var cmdList = document.getElementById("cmd-list");
    var cmdItems = [];
    var cmdIdx = 0;

    function collectCmdItems() {
      var list = [];
      var seenHref = {};
      document.querySelectorAll(".topnav a[href]").forEach(function (a) {
        var href = a.getAttribute("href");
        if (!href || seenHref[href]) return;
        seenHref[href] = true;
        list.push({ title: a.textContent.trim(), group: "주요 바로가기", code: "TOP", href: href, external: false });
      });
      document.querySelectorAll("#side-menu .side__menu").forEach(function (m) {
        var mTitle = m.querySelector(".side__menu-title button");
        var gName = mTitle ? mTitle.textContent.replace("›", "").trim() : "메뉴";
        m.querySelectorAll("a[data-screen]").forEach(function (a) {
          var href = a.getAttribute("href");
          var code = a.getAttribute("data-screen") || "";
          var name = a.textContent.replace("(새 창)", "").trim();
          list.push({ title: name, group: gName, code: code, href: href, external: a.hasAttribute("data-external") });
        });
      });
      return list;
    }

    function renderCmdList(q) {
      if (!cmdItems.length) cmdItems = collectCmdItems();
      var term = (q || "").trim().toLowerCase();
      var filtered = cmdItems.filter(function (it) {
        if (!term) return true;
        return it.title.toLowerCase().indexOf(term) !== -1 ||
               it.group.toLowerCase().indexOf(term) !== -1 ||
               it.code.toLowerCase().indexOf(term) !== -1;
      });
      cmdList.innerHTML = "";
      if (!filtered.length) {
        var emptyLi = document.createElement("li");
        emptyLi.className = "cmd-empty";
        emptyLi.textContent = "일치하는 화면이 없습니다.";
        cmdList.appendChild(emptyLi);
        return;
      }
      cmdIdx = Math.min(cmdIdx, filtered.length - 1);
      filtered.forEach(function (it, idx) {
        var li = document.createElement("li");
        li.className = "cmd-item" + (idx === cmdIdx ? " is-active" : "");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", idx === cmdIdx ? "true" : "false");
        li.innerHTML = '<span class="cmd-item__group">' + it.group + '</span>' +
          '<strong class="cmd-item__title">' + it.title + '</strong>' +
          (it.code ? '<code class="cmd-item__code">' + it.code + '</code>' : "");
        li.addEventListener("mouseenter", function () {
          cmdIdx = idx;
          updateCmdActive();
        });
        li.addEventListener("click", function () {
          if (it.external) window.open(it.href, "_blank", "noopener");
          else window.location.href = it.href;
          closeCmd();
        });
        cmdList.appendChild(li);
      });
    }

    function updateCmdActive() {
      var rows = cmdList.querySelectorAll(".cmd-item");
      rows.forEach(function (r, i) {
        var active = i === cmdIdx;
        r.classList.toggle("is-active", active);
        r.setAttribute("aria-selected", active ? "true" : "false");
        if (active && r.scrollIntoView) r.scrollIntoView({ block: "nearest" });
      });
    }

    function openCmd() {
      cmdLayer.hidden = false;
      cmdIdx = 0;
      if (cmdInput) {
        cmdInput.value = "";
        renderCmdList("");
        cmdInput.focus();
      }
    }

    function closeCmd() {
      cmdLayer.hidden = true;
      focusScan();
    }

    document.querySelectorAll("[data-cmd-open]").forEach(function (b) { b.addEventListener("click", openCmd); });
    cmdLayer.querySelectorAll("[data-cmd-close]").forEach(function (b) { b.addEventListener("click", closeCmd); });
    cmdLayer.addEventListener("click", function (e) { if (e.target === cmdLayer) closeCmd(); });
    if (cmdInput) {
      cmdInput.addEventListener("input", function () {
        cmdIdx = 0;
        renderCmdList(cmdInput.value);
      });
    }
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        if (cmdLayer.hidden) openCmd(); else closeCmd();
        return;
      }
      if (cmdLayer.hidden) return;
      if (e.key === "Escape") { e.preventDefault(); closeCmd(); return; }
      var rows = cmdList.querySelectorAll(".cmd-item");
      if (!rows.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        cmdIdx = (cmdIdx + 1) % rows.length;
        updateCmdActive();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        cmdIdx = (cmdIdx - 1 + rows.length) % rows.length;
        updateCmdActive();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (rows[cmdIdx]) rows[cmdIdx].click();
      }
    });
  }

  /* 현장·실무 사용성 도우미 (Usability Helpers)
     1. 1클릭 전량 입력 (`button[data-fill-qty="120.000"]`) — 자재 불출(MAT-020) 등에서 가용 수량을 한 번에 채운다.
     2. 출하 지시(SHP-010) 제품 LOT 선택 시 수량 칸이 비어 있으면 선택한 LOT의 가용 수량을 자동으로 채운다.
     3. 생산일보(PRD-010) 생산·양품 수량 입력 시 로스 수량(`생산 - 양품`, 0 이상)을 자동 계산한다.
     4. 검사일보(INS-010) 불량유형별 수량 입력 시 불량 합계를 자동으로 채운다.
     5. 검색 필터(`form.filters`)에 시작일·종료일(`date_from`/`date_to` 또는 `due_from`/`due_to`)이 있으면
        「오늘 · 이번 달 · 최근 3개월」 1클릭 기간 선택 단추를 붙여 날짜 입력 수고를 줄인다. */
  document.addEventListener("click", function (e) {
    var fillBtn = e.target.closest ? e.target.closest("[data-fill-qty]") : null;
    if (!fillBtn) return;
    var val = fillBtn.getAttribute("data-fill-qty");
    var form = fillBtn.closest("form") || fillBtn.closest("tr");
    if (!form) return;
    var input = form.querySelector('input[name="qty"]');
    if (input) {
      input.value = val;
      input.focus();
    }
  });

  document.querySelectorAll('select[name="stock_id"]').forEach(function (sel) {
    sel.addEventListener("change", function () {
      var row = sel.closest(".form-grid") || sel.closest("form");
      if (!row) return;
      var qtyInput = row.querySelector('input[name="qty"]');
      if (!qtyInput || qtyInput.value.trim() !== "") return;
      var opt = sel.options[sel.selectedIndex];
      if (!opt) return;
      var m = opt.text.match(/가용\s*([0-9.,]+)/);
      if (m && m[1]) qtyInput.value = m[1].replace(/,/g, "");
    });
  });

  document.querySelectorAll("form").forEach(function (form) {
    var prod = form.querySelector('input[name="produced_qty"]');
    var good = form.querySelector('input[name="good_qty"]');
    var loss = form.querySelector('input[name="loss_qty"]');
    if (prod && good && loss) {
      function syncLoss() {
        var p = parseFloat(prod.value);
        var g = parseFloat(good.value);
        if (!isNaN(p) && !isNaN(g) && p >= g) {
          var diff = Math.round((p - g) * 1000) / 1000;
          loss.value = String(diff);
        }
      }
      prod.addEventListener("input", syncLoss);
      good.addEventListener("input", syncLoss);
    }
    var defectTotal = form.querySelector('input[name="defect_qty"]');
    var defectCodes = form.querySelectorAll('input[name="defect_code_qty"]');
    if (defectTotal && defectCodes.length) {
      defectCodes.forEach(function (inp) {
        inp.addEventListener("input", function () {
          var sum = 0;
          var any = false;
          defectCodes.forEach(function (c) {
            var v = parseFloat(c.value);
            if (!isNaN(v) && v > 0) { sum += v; any = true; }
          });
          if (any) defectTotal.value = String(Math.round(sum * 1000) / 1000);
        });
      });
    }
  });

  function fmtDate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }
  document.querySelectorAll("form.filters").forEach(function (f) {
    var fromEl = f.querySelector('input[type="date"][name="date_from"], input[type="date"][name="due_from"]');
    var toEl = f.querySelector('input[type="date"][name="date_to"], input[type="date"][name="due_to"]');
    if (!fromEl || !toEl) return;
    var box = document.createElement("div");
    box.className = "date-presets";
    box.setAttribute("aria-label", "기간 빠른 선택");
    var presets = [
      { label: "오늘", fn: function () { var t = new Date(); return [fmtDate(t), fmtDate(t)]; } },
      { label: "이번 달", fn: function () { var t = new Date(); return [fmtDate(new Date(t.getFullYear(), t.getMonth(), 1)), fmtDate(t)]; } },
      { label: "최근 3개월", fn: function () { var t = new Date(); return [fmtDate(new Date(t.getFullYear(), t.getMonth() - 2, 1)), fmtDate(t)]; } }
    ];
    presets.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-sm";
      b.textContent = p.label;
      b.addEventListener("click", function () {
        var r = p.fn();
        fromEl.value = r[0];
        toEl.value = r[1];
        if (f.requestSubmit) f.requestSubmit(); else f.submit();
      });
      box.appendChild(b);
    });
    var toField = toEl.closest(".field");
    if (toField && toField.parentNode === f) {
      f.insertBefore(box, toField.nextSibling);
    }
  });

  /* 첫 입력 포커스 — 스캔칸이 없고 다른 것이 포커스를 갖지 않았을 때 본문의 첫 입력칸 */
  if (!scan && (!document.activeElement || document.activeElement === document.body) && !popupOpen()) {
    var first = document.querySelector("main input:not([type=hidden]):not([disabled]), main select:not([disabled]), main textarea:not([disabled])");
    if (first) first.focus({ preventScroll: true });
  }
  });
})();
