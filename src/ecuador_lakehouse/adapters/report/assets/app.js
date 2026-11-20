/*
 * Static report application (S16).
 * No frameworks, no network: the page data is embedded as JSON and ECharts is
 * vendored locally. Everything degrades to an explicit empty or error state.
 */
(function () {
  "use strict";

  var THEME_KEY = "lakehouse-theme";
  var CHARTS = Object.create(null);
  var RENDERERS = Object.create(null);

  /* ---------------------------------------------------------------- helpers */

  function $(id) {
    return document.getElementById(id);
  }

  function usd(value) {
    if (value === null || value === undefined || Number.isNaN(value)) { return "n/a"; }
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2
    }).format(value);
  }

  function usdExact(value) {
    if (value === null || value === undefined || Number.isNaN(value)) { return "n/a"; }
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD", maximumFractionDigits: 0
    }).format(value);
  }

  function pct(value, digits) {
    if (value === null || value === undefined || Number.isNaN(value)) { return "n/a"; }
    var fixed = typeof digits === "number" ? digits : 2;
    return (value * 100).toFixed(fixed) + "%";
  }

  function compact(value) {
    if (value === null || value === undefined || Number.isNaN(value)) { return "n/a"; }
    return new Intl.NumberFormat("en-US", {
      notation: "compact", maximumFractionDigits: 2
    }).format(value);
  }

  function monthLabel(iso) {
    if (!iso) { return ""; }
    return String(iso).slice(0, 7);
  }

  function setText(selector, text) {
    var nodes = document.querySelectorAll("[data-kpi=\"" + selector + "\"]");
    for (var index = 0; index < nodes.length; index += 1) {
      nodes[index].textContent = text;
    }
  }

  function readData() {
    var page = document.body.getAttribute("data-page") || "";
    var block = $("data-" + page);
    if (!block) {
      showEmpty();
      return null;
    }
    try {
      return JSON.parse(block.textContent);
    } catch (error) {
      showError("The embedded report data could not be parsed: " + error.message);
      return null;
    }
  }

  function showEmpty() {
    var empty = $("empty-state");
    if (empty) { empty.hidden = false; }
  }

  function showError(message) {
    var banner = $("error-banner");
    if (!banner) { return; }
    banner.hidden = false;
    banner.textContent = "";
    var title = document.createElement("strong");
    title.textContent = "Report error. ";
    banner.appendChild(title);
    banner.appendChild(document.createTextNode(message));
  }

  /* ----------------------------------------------------------------- theme */

  function currentTheme() {
    var theme = document.documentElement.getAttribute("data-theme");
    return theme === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch (error) { /* storage can be unavailable under file:// or private mode */ }
    syncThemeButton(theme);
    renderAll();
  }

  function syncThemeButton(theme) {
    var button = $("theme-toggle");
    if (!button) { return; }
    var next = theme === "dark" ? "light" : "dark";
    button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    button.setAttribute("aria-label", "Switch to " + next + " theme");
    button.textContent = next === "dark" ? "Dark theme" : "Light theme";
  }

  function initTheme() {
    syncThemeButton(currentTheme());
    var button = $("theme-toggle");
    if (button) {
      button.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    }
    if (window.matchMedia) {
      var media = window.matchMedia("(prefers-color-scheme: dark)");
      var listener = function (event) {
        var stored = null;
        try { stored = window.localStorage.getItem(THEME_KEY); } catch (error) { stored = null; }
        if (stored !== "light" && stored !== "dark") {
          document.documentElement.setAttribute("data-theme", event.matches ? "dark" : "light");
          syncThemeButton(currentTheme());
          renderAll();
        }
      };
      if (media.addEventListener) { media.addEventListener("change", listener); }
    }
  }

  /* ---------------------------------------------------------------- charts */

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
  }

  function palette() {
    var colors = [];
    for (var index = 1; index <= 8; index += 1) { colors.push(token("chart-" + index)); }
    return colors;
  }

  function axisStyle() {
    return {
      axisLine: { lineStyle: { color: token("border") } },
      axisTick: { lineStyle: { color: token("border") } },
      axisLabel: { color: token("text-muted"), fontFamily: token("font-sans") },
      splitLine: { lineStyle: { color: token("border"), opacity: 0.55 } }
    };
  }

  function baseOption() {
    return {
      color: palette(),
      textStyle: { color: token("text"), fontFamily: token("font-sans") },
      animationDuration: 350,
      grid: { left: 56, right: 24, top: 48, bottom: 48, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: token("surface"),
        borderColor: token("border"),
        textStyle: { color: token("text"), fontFamily: token("font-sans") }
      },
      legend: {
        top: 0,
        textStyle: { color: token("text-muted"), fontFamily: token("font-sans") },
        type: "scroll"
      }
    };
  }

  function draw(id, option) {
    var element = $(id);
    if (!element) { return; }
    var chart = CHARTS[id];
    if (!chart) {
      chart = window.echarts.init(element, null, { renderer: "canvas" });
      CHARTS[id] = chart;
      if (window.ResizeObserver) {
        var observer = new ResizeObserver(function () { chart.resize(); });
        observer.observe(element);
        element._lakehouseObserver = observer;
      } else {
        window.addEventListener("resize", function () { chart.resize(); });
      }
    }
    chart.setOption(option, true);
    chart.resize();
  }

  function renderAll() {
    var page = document.body.getAttribute("data-page") || "";
    var render = RENDERERS[page];
    if (render) {
      try {
        render();
      } catch (error) {
        showError(error.message);
      }
    }
  }

  /* ---------------------------------------------------------------- tables */

  function buildRow(values) {
    var row = document.createElement("tr");
    for (var index = 0; index < values.length; index += 1) {
      var spec = values[index];
      var cell = document.createElement("td");
      cell.textContent = spec.text === null || spec.text === undefined ? "" : String(spec.text);
      if (spec.className) { cell.className = spec.className; }
      if (spec.value !== undefined && spec.value !== null) {
        cell.setAttribute("data-value", String(spec.value));
      }
      row.appendChild(cell);
    }
    return row;
  }

  function fillTable(tbody, rows) {
    if (!tbody) { return; }
    tbody.textContent = "";
    for (var index = 0; index < rows.length; index += 1) {
      tbody.appendChild(buildRow(rows[index]));
    }
    var table = tbody.closest("table");
    if (table) { table._lakehouseRows = rows; }
  }

  function compare(left, right) {
    var leftNumber = Number(left);
    var rightNumber = Number(right);
    if (left !== "" && right !== "" && !Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) {
      return leftNumber - rightNumber;
    }
    return String(left).localeCompare(String(right), "en");
  }

  function initSortable() {
    var tables = document.querySelectorAll("table[data-sortable]");
    for (var index = 0; index < tables.length; index += 1) {
      (function (table) {
        var buttons = table.querySelectorAll("button.sort");
        for (var b = 0; b < buttons.length; b += 1) {
          (function (button) {
            button.addEventListener("click", function () {
              var header = button.closest("th");
              var column = header.cellIndex;
              var ascending = header.getAttribute("aria-sort") !== "ascending";
              var headers = table.querySelectorAll("thead th");
              for (var h = 0; h < headers.length; h += 1) { headers[h].removeAttribute("aria-sort"); }
              header.setAttribute("aria-sort", ascending ? "ascending" : "descending");
              var body = table.querySelector("tbody");
              var rows = Array.prototype.slice.call(body.querySelectorAll("tr"));
              rows.sort(function (left, right) {
                var leftCell = left.children[column];
                var rightCell = right.children[column];
                var leftValue = leftCell.getAttribute("data-value") || leftCell.textContent.trim();
                var rightValue = rightCell.getAttribute("data-value") || rightCell.textContent.trim();
                return ascending ? compare(leftValue, rightValue) : compare(rightValue, leftValue);
              });
              for (var r = 0; r < rows.length; r += 1) { body.appendChild(rows[r]); }
            });
          })(buttons[b]);
        }
      })(tables[index]);
    }
  }

  /* --------------------------------------------------------------- overview */

  function renderOverview(data) {
    var kpis = data.kpis;
    setText("latest_full_year", kpis.latest_full_year);
    setText("latest_full_year_total", usd(kpis.latest_full_year_total_usd));
    setText(
      "latest_full_year_detail",
      kpis.latest_full_year_yoy === null
        ? "Full year"
        : (kpis.latest_full_year_yoy >= 0 ? "+" : "") + pct(kpis.latest_full_year_yoy, 1) + " vs. prior year"
    );
    setText("inflation_period", "Dec 2024");
    setText("inflation_value", pct(kpis.inflation_dec_2024));
    setText("ratio_year", "2020");
    setText("ratio_value", pct(kpis.ratio_2020, 1));
    setText("tests_value", kpis.tests_passed + "/" + kpis.tests_total);
    setText("tests_detail", kpis.tests_failed + " failing · quality gate");
    setText("tests_passed", kpis.tests_passed);
    setText("tests_failed", kpis.tests_failed);
    setText("batches_value", kpis.batches);
    setText("mode", data.mode === "sample" ? "Sample data" : "Full data");

    var labels = [];
    var nominal = [];
    var real = [];
    for (var index = 0; index < data.monthly.length; index += 1) {
      var row = data.monthly[index];
      labels.push(monthLabel(row.date));
      nominal.push(row.nominal_usd);
      real.push(row.real_usd);
    }
    var option = baseOption();
    option.grid = { left: 64, right: 24, top: 48, bottom: 56, containLabel: true };
    option.tooltip.valueFormatter = function (value) { return usdExact(value); };
    option.xAxis = Object.assign({ type: "category", data: labels, boundaryGap: false }, axisStyle());
    option.yAxis = Object.assign({ type: "value", name: "USD" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return usd(value); } }
    });
    option.series = [
      { name: "Nominal", type: "line", data: nominal, showSymbol: false, smooth: true, areaStyle: { opacity: 0.12 } },
      { name: "Real 2014 USD", type: "line", data: real, showSymbol: false, smooth: true, connectNulls: false }
    ];
    draw("chart-overview-monthly", option);
  }

  /* -------------------------------------------------------------------- tax */

  function renderTax(data) {
    var from = $("tax-from");
    var to = $("tax-to");
    var provinceYear = $("tax-province-year");
    var groups = data.groups;
    var years = data.years;

    function options(select, selected) {
      select.textContent = "";
      for (var index = 0; index < years.length; index += 1) {
        var option = document.createElement("option");
        option.value = String(years[index]);
        option.textContent = String(years[index]);
        if (String(years[index]) === String(selected)) { option.selected = true; }
        select.appendChild(option);
      }
    }

    if (!from._lakehouseReady) {
      options(from, years[0]);
      options(to, years[years.length - 1]);
      options(provinceYear, years[years.length - 1]);
      from._lakehouseReady = true;
      from.addEventListener("change", function () { renderTax(data); });
      to.addEventListener("change", function () { renderTax(data); });
      provinceYear.addEventListener("change", function () { renderTax(data); });
    }

    var start = Number(from.value);
    var end = Number(to.value);
    if (start > end) {
      var swap = start;
      start = end;
      end = swap;
    }

    var months = [];
    var seen = Object.create(null);
    var filtered = [];
    for (var index = 0; index < data.monthly.length; index += 1) {
      var row = data.monthly[index];
      if (row.year < start || row.year > end) { continue; }
      filtered.push(row);
      if (!seen[row.date]) {
        seen[row.date] = true;
        months.push(row.date);
      }
    }
    months.sort();
    var position = Object.create(null);
    for (var m = 0; m < months.length; m += 1) { position[months[m]] = m; }
    var series = [];
    for (var g = 0; g < groups.length; g += 1) {
      var group = groups[g];
      var values = new Array(months.length);
      for (var v = 0; v < months.length; v += 1) { values[v] = 0; }
      for (var f = 0; f < filtered.length; f += 1) {
        if (filtered[f].group !== group) { continue; }
        values[position[filtered[f].date]] += filtered[f].nominal_usd;
      }
      series.push({ name: group, type: "line", stack: "total", areaStyle: {}, showSymbol: false, data: values });
    }

    var option = baseOption();
    option.tooltip.valueFormatter = function (value) { return usdExact(value); };
    option.xAxis = Object.assign({ type: "category", data: months, boundaryGap: false }, axisStyle(), {
      axisLabel: {
        color: token("text-muted"),
        formatter: function (value) { return String(value).slice(0, 7); }
      }
    });
    option.yAxis = Object.assign({ type: "value", name: "USD" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return usd(value); } }
    });
    option.series = series;
    draw("chart-tax-groups", option);

    var yearKey = String(provinceYear.value);
    var provinces = data.provinces[yearKey] || [];
    var provinceOption = baseOption();
    provinceOption.legend = { show: false };
    provinceOption.grid = { left: 24, right: 56, top: 16, bottom: 24, containLabel: true };
    provinceOption.tooltip = { trigger: "item", valueFormatter: function (value) { return usdExact(value); } };
    provinceOption.xAxis = Object.assign({ type: "value" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return usd(value); } }
    });
    provinceOption.yAxis = Object.assign({
      type: "category",
      data: provinces.map(function (row) { return row.name; }).reverse()
    }, axisStyle());
    provinceOption.series = [{
      name: yearKey,
      type: "bar",
      data: provinces.map(function (row) { return row.collected_usd; }).reverse(),
      itemStyle: { borderRadius: [0, 4, 4, 0] }
    }];
    draw("chart-tax-provinces", provinceOption);

    var rows = data.top_lines.map(function (line) {
      return [
        { text: line.tax_name },
        { text: line.tax_group_name },
        { text: usdExact(line.total_collected_usd), value: line.total_collected_usd, className: "numeric" },
        { text: line.last_year, value: line.last_year, className: "numeric" }
      ];
    });
    fillTable($("tax-top-lines"), rows);
  }

  /* ----------------------------------------------------------------- prices */

  function renderPrices(data) {
    var select = $("price-area");
    if (!select._lakehouseReady) {
      for (var index = 0; index < data.areas.length; index += 1) {
        var option = document.createElement("option");
        option.value = data.areas[index];
        option.textContent = data.areas[index];
        select.appendChild(option);
      }
      select._lakehouseReady = true;
      select.addEventListener("change", function () { renderPrices(data); });
    }
    var area = select.value || data.areas[0];
    setText("latest_month", data.latest_month);

    var series = data.series.filter(function (row) { return row.area === area; });
    var labels = series.map(function (row) { return monthLabel(row.date); });
    var indexOption = baseOption();
    indexOption.tooltip = { trigger: "axis", valueFormatter: function (value) { return value; } };
    indexOption.grid = { left: 64, right: 72, top: 48, bottom: 56, containLabel: true };
    indexOption.xAxis = Object.assign({ type: "category", data: labels, boundaryGap: false }, axisStyle());
    indexOption.yAxis = [
      Object.assign({ type: "value", name: "Index" }, axisStyle(), {
        axisLabel: { color: token("text-muted"), formatter: function (value) { return value.toFixed(0); } }
      }),
      Object.assign({ type: "value", name: "YoY", position: "right" }, axisStyle(), {
        axisLabel: { color: token("text-muted"), formatter: function (value) { return pct(value, 0); } },
        splitLine: { show: false }
      })
    ];
    indexOption.series = [
      { name: "Index", type: "line", data: series.map(function (row) { return row.index_value; }), showSymbol: false },
      {
        name: "YoY", type: "line", yAxisIndex: 1, showSymbol: false,
        data: series.map(function (row) { return row.yoy; })
      }
    ];
    draw("chart-price-index", indexOption);

    var divisions = data.divisions.filter(function (row) { return row.area === area; });
    divisions.sort(function (left, right) { return (left.yoy || 0) - (right.yoy || 0); });
    var divisionOption = baseOption();
    divisionOption.legend = { show: false };
    divisionOption.grid = { left: 24, right: 56, top: 16, bottom: 24, containLabel: true };
    divisionOption.tooltip = {
      trigger: "item",
      valueFormatter: function (value) { return pct(value); }
    };
    divisionOption.xAxis = Object.assign({ type: "value" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return pct(value, 0); } }
    });
    divisionOption.yAxis = Object.assign({
      type: "category",
      data: divisions.map(function (row) { return row.name; })
    }, axisStyle());
    divisionOption.series = [{
      name: "YoY",
      type: "bar",
      data: divisions.map(function (row) { return row.yoy; }),
      itemStyle: { borderRadius: [0, 4, 4, 0] }
    }];
    draw("chart-price-divisions", divisionOption);

    divisions.sort(function (left, right) { return (right.yoy || 0) - (left.yoy || 0); });
    fillTable($("price-divisions"), divisions.map(function (row) {
      return [
        { text: row.name },
        { text: pct(row.yoy), value: row.yoy, className: "numeric" },
        { text: pct(row.mom), value: row.mom, className: "numeric" }
      ];
    }));
  }

  /* ------------------------------------------------------------------ macro */

  function renderMacro(data) {
    var select = $("macro-year");
    var years = data.years;
    if (!select._lakehouseReady) {
      for (var index = years.length - 1; index >= 0; index -= 1) {
        var option = document.createElement("option");
        option.value = String(years[index]);
        option.textContent = String(years[index]);
        select.appendChild(option);
      }
      select._lakehouseReady = true;
      select.addEventListener("change", function () { renderMacro(data); });
    }
    var year = Number(select.value || years[years.length - 1]);
    var industries = data.industries.filter(function (row) { return row.year === year; });
    industries.sort(function (left, right) { return left.value_usd - right.value_usd; });

    var element = $("chart-macro-industries");
    if (element) {
      element.style.height = Math.max(480, industries.length * 22 + 80) + "px";
    }
    var industryOption = baseOption();
    industryOption.legend = { show: false };
    industryOption.grid = { left: 24, right: 72, top: 16, bottom: 24, containLabel: true };
    industryOption.tooltip = {
      trigger: "item",
      valueFormatter: function (value) { return usdExact(value); }
    };
    industryOption.xAxis = Object.assign({ type: "value" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return usd(value); } }
    });
    industryOption.yAxis = Object.assign({
      type: "category",
      data: industries.map(function (row) { return row.name; }),
      axisLabel: {
        color: token("text-muted"),
        width: 220,
        overflow: "truncate",
        fontFamily: token("font-sans")
      }
    }, axisStyle());
    industryOption.series = [{
      name: "GDP contribution",
      type: "bar",
      data: industries.map(function (row) { return row.value_usd; }),
      itemStyle: { borderRadius: [0, 4, 4, 0] }
    }];
    draw("chart-macro-industries", industryOption);

    var complete = data.ratios.filter(function (row) { return row.is_complete; });
    var ratioOption = baseOption();
    ratioOption.legend = { show: false };
    ratioOption.tooltip = { trigger: "axis", valueFormatter: function (value) { return pct(value, 2); } };
    ratioOption.grid = { left: 64, right: 24, top: 24, bottom: 48, containLabel: true };
    ratioOption.xAxis = Object.assign({
      type: "category",
      data: complete.map(function (row) { return String(row.year); })
    }, axisStyle());
    ratioOption.yAxis = Object.assign({ type: "value", name: "ratio" }, axisStyle(), {
      axisLabel: { color: token("text-muted"), formatter: function (value) { return pct(value, 0); } }
    });
    ratioOption.series = [{
      name: "SRI / GDP",
      type: "line",
      data: complete.map(function (row) { return row.ratio; }),
      label: { show: true, formatter: function (params) { return pct(params.value, 1); } }
    }];
    draw("chart-macro-ratio", ratioOption);

    fillTable($("macro-ratios"), data.ratios.map(function (row) {
      return [
        { text: row.year, value: row.year },
        { text: usdExact(row.sri_usd), value: row.sri_usd, className: "numeric" },
        { text: row.gdp_usd === null ? "n/a" : usdExact(row.gdp_usd), value: row.gdp_usd || 0, className: "numeric" },
        { text: row.ratio === null ? "n/a" : pct(row.ratio), value: row.ratio || 0, className: "numeric" },
        { text: row.is_complete ? "Yes" : "No", value: row.is_complete ? 1 : 0 }
      ];
    }));
  }

  /* ---------------------------------------------------------------- quality */

  function renderQuality(data) {
    setText("tests_total", data.tests.total);
    setText("quality_detail", data.tests.passed + " passed · " + data.tests.failed + " failed");
    setText("batches_value", data.batches.length);
    var martRows = 0;
    for (var index = 0; index < data.row_counts.length; index += 1) {
      if (data.row_counts[index].layer === "marts") { martRows += data.row_counts[index].rows; }
    }
    setText("mart_rows", compact(martRows));

    fillTable($("quality-layers"), data.tests.layers.map(function (row) {
      return [
        { text: row.layer },
        { text: row.total, value: row.total, className: "numeric" },
        { text: row.passed, value: row.passed, className: "numeric" },
        { text: row.failed, value: row.failed, className: "numeric" }
      ];
    }));
    fillTable($("quality-rows"), data.row_counts.map(function (row) {
      return [
        { text: row.layer },
        { text: row.table, className: "mono" },
        { text: String(row.rows), value: row.rows, className: "numeric" }
      ];
    }));
    fillTable($("quality-batches"), data.batches.map(function (row) {
      return [
        { text: row.source_id },
        { text: row.partition },
        { text: String(row.rows), value: row.rows, className: "numeric" },
        { text: row.status },
        { text: row.loaded_at ? String(row.loaded_at).replace("T", " ").slice(0, 19) : "" }
      ];
    }));
  }

  /* ---------------------------------------------------------------- sources */

  function renderSources(data) {
    setText("checked_at", data.checked_at);
    setText("file_count", data.files.length);
    var labels = {
      sri_tax: "SRI — tax collection",
      bce_cnt: "BCE — national accounts",
      inec_cpi: "INEC — consumer prices"
    };
    var seen = Object.create(null);
    var licenseRows = [];
    for (var index = 0; index < data.files.length; index += 1) {
      var file = data.files[index];
      if (seen[file.source_id]) { continue; }
      seen[file.source_id] = true;
      licenseRows.push([
        { text: labels[file.source_id] || file.source_id },
        { text: file.license_id + " (" + (file.license_id === "cc-by-4.0" ? "CC BY 4.0" : "Creative Commons Attribution") + ")" }
      ]);
    }
    fillTable($("sources-licenses"), licenseRows);
    fillTable($("sources-files"), data.files.map(function (file) {
      return [
        { text: file.source_id },
        { text: file.partition },
        { text: String(file.bytes), value: file.bytes, className: "numeric" },
        { text: file.mutable ? "Yes" : "No", value: file.mutable ? 1 : 0 },
        { text: file.sha256, className: "mono" }
      ];
    }));
  }

  /* ------------------------------------------------------------------- boot */

  function boot() {
    initTheme();
    var page = document.body.getAttribute("data-page") || "";
    var renderers = {
      overview: renderOverview,
      tax: renderTax,
      prices: renderPrices,
      macro: renderMacro,
      quality: renderQuality,
      sources: renderSources
    };
    var data = readData();
    if (data && renderers[page]) {
      RENDERERS[page] = function () { renderers[page](data); };
      try {
        renderers[page](data);
      } catch (error) {
        showError(error.message);
      }
    } else if (data) {
      RENDERERS[page] = function () {};
    }
    initSortable();
    document.documentElement.setAttribute("data-ready", "true");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
