const StudyCurves = (() => {
  'use strict';

  function roundedDecimal(value, places = 2) {
    const [coefficient, exponentText = '0'] = Math.abs(value).toString().toLowerCase().split('e');
    const [integer, fraction = ''] = coefficient.split('.');
    const digits = BigInt(integer + fraction);
    const shift = Number(exponentText) - fraction.length + places;
    let rounded;
    if (shift >= 0) rounded = digits * 10n ** BigInt(shift);
    else {
      const divisor = 10n ** BigInt(-shift);
      rounded = digits / divisor + (digits % divisor * 2n >= divisor ? 1n : 0n);
    }
    const text = rounded.toString().padStart(places + 1, '0');
    return (value < 0 && rounded !== 0n ? '−' : '') + text.slice(0, -places) + '.' + text.slice(-places);
  }

  function tickText(value) {
    if (value === 0) return '0';
    if (Math.abs(value) >= 10000 || Math.abs(value) < .01) {
      const [mantissa, exponent] = value.toExponential().split('e');
      let rounded = roundedDecimal(Number(mantissa));
      let power = Number(exponent);
      if (rounded === '10.00' || rounded === '−10.00') {
        rounded = rounded[0] === '−' ? '−1.00' : '1.00';
        power += 1;
      }
      return rounded + 'e' + (power < 0 ? '−' + Math.abs(power) : '+' + power);
    }
    return roundedDecimal(value);
  }

  function hasCurve(record) {
    if (record.state !== 'ready' || !Array.isArray(record.x) || !Array.isArray(record.y)
        || !record.x.length || record.x.length !== record.y.length) return false;
    return record.x.every(Number.isFinite) && record.y.every(Number.isFinite);
  }

  function bounds(records) {
    const result = {x: [0, 0], y: [0, 0]};
    for (const record of records) {
      if (!hasCurve(record)) continue;
      for (let index = 0; index < record.x.length; index++) {
        result.x[0] = Math.min(result.x[0], record.x[index]);
        result.x[1] = Math.max(result.x[1], record.x[index]);
        result.y[0] = Math.min(result.y[0], record.y[index]);
        result.y[1] = Math.max(result.y[1], record.y[index]);
      }
    }
    if (result.x[0] === result.x[1]) result.x[1] = 1;
    if (result.y[0] === result.y[1]) result.y[1] = 1;
    return result;
  }

  function position(value, limits, start, end) {
    const magnitude = Math.max(Math.abs(limits[0]), Math.abs(limits[1]));
    const low = limits[0] / magnitude;
    const high = limits[1] / magnitude;
    return start + (value / magnitude - low) / (high - low) * (end - start);
  }

  function projected(record, limits, area) {
    const points = [];
    if (!hasCurve(record)) return points;
    for (let index = 0; index < record.x.length; index++) {
      points.push({x: position(record.x[index], limits.x, area.left, area.right),
        y: position(record.y[index], limits.y, area.bottom, area.top), index});
    }
    return points;
  }

  function nearestSample(series, x, y, tolerance = 12) {
    let nearest = null;
    let best = tolerance * tolerance;
    for (const item of series) {
      const points = item.points;
      for (let index = 0; index < points.length; index++) {
        const first = points[index];
        const second = points[index + 1] || first;
        const dx = second.x - first.x, dy = second.y - first.y;
        const span = dx * dx + dy * dy;
        const fraction = span ? Math.max(0, Math.min(1, ((x - first.x) * dx + (y - first.y) * dy) / span)) : 0;
        const distance = (x - first.x - dx * fraction) ** 2 + (y - first.y - dy * fraction) ** 2;
        if (distance > best || (nearest && distance === best)) continue;
        const recorded = (x - first.x) ** 2 + (y - first.y) ** 2 <= (x - second.x) ** 2 + (y - second.y) ** 2 ? first : second;
        best = distance;
        nearest = {record: item.record, index: recorded.index, point: recorded};
      }
    }
    return nearest;
  }

  function canOverlay(payload) {
    return payload.overlay_allowed === true && Array.isArray(payload.records)
      && payload.records.length >= 2 && payload.records.every(hasCurve);
  }

  return {tickText, hasCurve, bounds, position, projected, nearestSample, canOverlay};
})();

if (typeof module !== 'undefined' && module.exports) module.exports = StudyCurves;

if (typeof document !== 'undefined') (() => {
  'use strict';

  const section = document.getElementById('study-curves');
  if (!section) return;
  const workspace = document.getElementById('study-workspace');
  const form = document.getElementById('study-curves-form');
  const status = document.getElementById('study-curves-status');
  const retry = document.getElementById('study-curves-retry');
  const toolbar = document.getElementById('study-curves-toolbar');
  const separate = document.getElementById('study-curves-separate');
  const overlay = document.getElementById('study-curves-overlay');
  const overlayNote = document.getElementById('study-curves-overlay-note');
  const scaleNote = document.getElementById('study-curves-scale-note');
  const separateView = document.getElementById('study-curves-records');
  const overlayView = document.getElementById('study-curves-overlay-view');
  const clearFocus = document.getElementById('study-curves-clear-focus');
  const palette = ['#087f8c', '#a36518', '#7653a2', '#327446'];
  const sourceLinks = new Map(Array.from(section.querySelectorAll('[data-curve-source]'), link => [Number(link.dataset.curveSource), link.href]));
  let payload = null;
  let loading = false;
  let controller = null;
  let active = null;
  const plots = [];
  const colors = new Map();

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function selectRecord(pk) {
    active = pk;
    clearFocus.hidden = active === null;
    for (const node of workspace.querySelectorAll('[data-study-object]')) {
      const selected = Number(node.dataset.studyObject) === pk;
      node.classList.toggle('is-study-active', selected);
      if (selected) node.style.setProperty('--study-focus-color', colors.get(pk));
      else node.style.removeProperty('--study-focus-color');
    }
    for (const node of section.querySelectorAll('[data-curve-record]')) {
      const selected = Number(node.dataset.curveRecord) === pk;
      node.classList.toggle('is-study-active', selected);
      node.querySelector('button')?.setAttribute('aria-pressed', String(selected));
    }
    for (const button of section.querySelectorAll('[data-curve-highlight]')) {
      button.setAttribute('aria-pressed', String(Number(button.dataset.curveHighlight) === pk));
    }
    for (const plot of plots) plot.draw();
    section.dataset.activeRecord = active === null ? '' : String(active);
  }

  function seriesLabel(record) {
    return `${record.y_label || 'Stress'} (${record.y_unit}) / ${record.x_label || 'Strain'} (${record.x_unit})`;
  }

  function buildPlot(parent, records, name) {
    const holder = element('div', 'study-curve-plot');
    const canvas = element('canvas');
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', name + '. Complete paired curve in recorded order. Use arrow keys to inspect samples.');
    canvas.textContent = 'The recorded response curve is available on the source record.';
    const hover = element('p', 'study-curve-hover');
    hover.setAttribute('role', 'status');
    holder.append(canvas);
    parent.append(holder, hover);
    const context = canvas.getContext('2d');
    const limits = StudyCurves.bounds(records);
    let series = [];
    let hovered = null;
    let keyboardIndex = 0;
    let width = 0, height = 0;

    function showSample(sample) {
      hovered = sample;
      hover.textContent = sample ? `${sample.record.title} · Sample ${sample.index} · X: ${sample.record.x[sample.index]} ${sample.record.x_unit} · Y: ${sample.record.y[sample.index]} ${sample.record.y_unit}` : '';
      canvas.dataset.sampleIndex = sample ? String(sample.index) : '';
      canvas.dataset.sampleRecord = sample ? String(sample.record.pk) : '';
      draw();
    }

    function axisTicks(values, axis, area, axisX, axisY) {
      const occupied = [];
      const ticks = [...new Set([0, ...values])];
      for (const value of ticks) {
        const label = StudyCurves.tickText(value);
        const x = axis === 'x' ? StudyCurves.position(value, values, area.left, area.right) : axisX - 8;
        const y = axis === 'y' ? StudyCurves.position(value, values, area.bottom, area.top) : axisY + 18;
        const measure = context.measureText(label).width;
        const box = axis === 'x' ? {start: x - measure / 2, end: x + measure / 2} : {start: y - 7, end: y + 7};
        if (occupied.some(other => box.start < other.end + 5 && box.end > other.start - 5)) continue;
        occupied.push(box);
        context.textAlign = axis === 'x' ? 'center' : 'right';
        context.textBaseline = axis === 'x' ? 'alphabetic' : 'middle';
        context.fillText(label, x, y);
        if (value !== 0) {
          context.beginPath();
          if (axis === 'x') { context.moveTo(x, axisY - 3); context.lineTo(x, axisY + 3); }
          else { context.moveTo(axisX - 3, y); context.lineTo(axisX + 3, y); }
          context.stroke();
        }
      }
    }

    function axisTitle(symbol, subscript, superscript, x, y) {
      context.save();
      context.font = 'italic 17px Georgia, serif';
      const symbolWidth = context.measureText(symbol).width;
      context.font = '12px Georgia, serif';
      const scriptWidth = Math.max(context.measureText(subscript).width, context.measureText(superscript).width);
      const left = x - (symbolWidth + scriptWidth + 1) / 2;
      context.textAlign = 'left'; context.textBaseline = 'alphabetic';
      context.font = 'italic 17px Georgia, serif';
      context.fillText(symbol, left, y);
      context.font = '12px Georgia, serif';
      context.fillText(subscript, left + symbolWidth + 1, y + 4);
      if (superscript) context.fillText(superscript, left + symbolWidth + 1, y - 7);
      context.restore();
    }

    function draw() {
      if (!width || !height) return;
      context.clearRect(0, 0, width, height);
      context.font = '12px "Open Sans", sans-serif';
      const widest = Math.max(...limits.y.map(value => context.measureText(StudyCurves.tickText(value)).width));
      const area = {left: Math.max(62, widest + 21), right: width - 34, top: 25, bottom: height - 48};
      if (area.right <= area.left) return;
      const axisX = StudyCurves.position(0, limits.x, area.left, area.right);
      const axisY = StudyCurves.position(0, limits.y, area.bottom, area.top);
      context.fillStyle = '#000';
      context.strokeStyle = '#000';
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(area.left, axisY); context.lineTo(area.right + 12, axisY);
      context.moveTo(axisX, area.bottom); context.lineTo(axisX, area.top - 12);
      context.stroke();
      context.beginPath();
      context.moveTo(area.right + 12, axisY); context.lineTo(area.right + 5, axisY - 4); context.lineTo(area.right + 5, axisY + 4);
      context.moveTo(axisX, area.top - 12); context.lineTo(axisX - 4, area.top - 5); context.lineTo(axisX + 4, area.top - 5);
      context.fill();
      axisTicks(limits.x, 'x', area, axisX, axisY);
      axisTicks(limits.y, 'y', area, axisX, axisY);
      const subscript = payload.component === 'equivalent' ? 'eq' : payload.component;
      axisTitle('ε', subscript, payload.strain === 'plastic' ? 'p' : '', (area.left + area.right) / 2, height - 10);
      context.save(); context.translate(15, (area.top + area.bottom) / 2); context.rotate(-Math.PI / 2);
      axisTitle('σ', subscript, '', 0, 0); context.restore();
      series = records.map(record => ({record, points: StudyCurves.projected(record, limits, area)}));
      for (const item of series) {
        context.strokeStyle = colors.get(item.record.pk);
        context.fillStyle = colors.get(item.record.pk);
        context.globalAlpha = active === null || item.record.pk === active || records.length === 1 ? 1 : .45;
        context.lineWidth = item.record.pk === active ? 2.8 : 2;
        context.beginPath();
        item.points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
        context.stroke();
        if (item.points.length === 1) {
          context.beginPath(); context.arc(item.points[0].x, item.points[0].y, 3, 0, 2 * Math.PI); context.fill();
        }
      }
      context.globalAlpha = 1;
      if (hovered) {
        const item = series.find(item => item.record.pk === hovered.record.pk);
        const point = item?.points[hovered.index];
        if (point) {
          context.fillStyle = colors.get(item.record.pk);
          context.beginPath(); context.arc(point.x, point.y, 5, 0, 2 * Math.PI); context.fill();
        }
      }
    }

    function resize() {
      const box = holder.getBoundingClientRect();
      if (!box.width || !box.height) return;
      width = box.width; height = box.height;
      const density = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = Math.round(width * density); canvas.height = Math.round(height * density);
      context.setTransform(density, 0, 0, density, 0, 0);
      draw();
    }

    function hit(event) {
      const box = canvas.getBoundingClientRect();
      const priority = [...series].sort((first, second) => Number(second.record.pk === active) - Number(first.record.pk === active));
      return StudyCurves.nearestSample(priority, event.clientX - box.left, event.clientY - box.top);
    }

    canvas.addEventListener('pointermove', event => showSample(hit(event)));
    canvas.addEventListener('pointerleave', () => showSample(null));
    canvas.addEventListener('blur', () => showSample(null));
    canvas.addEventListener('click', event => { const sample = hit(event); if (sample) selectRecord(sample.record.pk); });
    canvas.addEventListener('keydown', event => {
      if (event.key === 'Escape') { showSample(null); return; }
      const item = series.find(item => item.record.pk === active) || series[0];
      if (!item) return;
      if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        event.preventDefault();
        if (event.key === 'Home') keyboardIndex = 0;
        else if (event.key === 'End') keyboardIndex = item.points.length - 1;
        else keyboardIndex = Math.max(0, Math.min(item.points.length - 1, keyboardIndex + (event.key === 'ArrowRight' ? 1 : -1)));
        showSample({record: item.record, index: keyboardIndex, point: item.points[keyboardIndex]});
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); selectRecord(item.record.pk);
      }
    });
    const plot = {draw, resize};
    plots.push(plot);
    if ('ResizeObserver' in window) new ResizeObserver(resize).observe(holder);
    else window.addEventListener('resize', resize);
    resize();
  }

  function render() {
    separateView.replaceChildren(); overlayView.replaceChildren(); plots.length = 0;
    payload.records.forEach((record, index) => colors.set(record.pk, palette[index]));
    for (const record of payload.records) {
      const card = element('article', 'study-curve-record');
      card.dataset.curveRecord = record.pk;
      card.style.setProperty('--curve-color', colors.get(record.pk));
      const heading = element('div', 'study-curve-record-heading');
      const title = element('button', 'study-curve-record-name', record.title);
      title.type = 'button'; title.setAttribute('aria-pressed', 'false');
      title.addEventListener('click', () => selectRecord(record.pk));
      heading.append(title);
      const source = sourceLinks.get(record.pk);
      if (source) { const link = element('a', '', 'Source'); link.href = source; heading.append(link); }
      card.append(heading, element('p', 'study-curve-record-units', seriesLabel(record)));
      if (StudyCurves.hasCurve(record)) {
        const origin = [record.calculated_y ? 'Calculated equivalent stress' : 'Supplied stress',
          record.calculated_x ? 'calculated equivalent strain' : 'supplied strain'].join('; ');
        card.append(element('p', 'study-curve-record-source', origin));
        if (record.x_count !== record.y_count) {
          card.append(element('p', 'study-curve-record-note', `${record.paired_count} paired samples plotted. The source has ${record.x_count} strain and ${record.y_count} stress values; unmatched tails are not plotted.`));
        }
        buildPlot(card, [record], record.title);
      } else card.append(element('p', 'study-curve-record-note', record.error || 'No complete curve is available for this selection. Open the source record to inspect its data.'));
      separateView.append(card);
    }
    separateView.hidden = false;
    toolbar.hidden = false;
    scaleNote.hidden = false;
    overlay.disabled = !StudyCurves.canOverlay(payload);
    overlay.title = overlay.disabled ? payload.overlay_reason || 'These records cannot share axes.' : 'Show the selected curves on shared axes';
    overlayNote.textContent = overlay.disabled ? payload.overlay_reason : 'Overlay uses the same recorded quantity, component and units. It does not establish scientific comparability.';
    overlayNote.hidden = false;
    if (!overlay.disabled) {
      const legend = element('div', 'study-curve-legend');
      for (const record of payload.records) {
        const button = element('button', '', record.title);
        button.type = 'button'; button.dataset.curveHighlight = record.pk;
        button.style.setProperty('--curve-color', colors.get(record.pk));
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', () => selectRecord(record.pk));
        legend.append(button);
      }
      overlayView.append(legend, element('p', 'study-curve-record-units', seriesLabel(payload.records[0])));
      buildPlot(overlayView, payload.records, 'Overlay of selected records');
    }
    document.getElementById('study-curves-guidance').hidden = !payload.records.some(StudyCurves.hasCurve);
    status.textContent = payload.records.some(StudyCurves.hasCurve) ? '' : 'No complete paired curves are available for the selected component and strain.';
    section.dataset.loaded = 'true';
    for (const plot of plots) plot.resize();
  }

  async function load() {
    if (loading || payload) return;
    loading = true; retry.hidden = true; status.dataset.error = 'false';
    status.textContent = 'Loading the selected curves…';
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const url = new URL(section.dataset.endpoint, location.href);
      url.searchParams.set('compare', section.dataset.selection);
      url.searchParams.set('curve_component', form.elements.curve_component.value);
      url.searchParams.set('curve_strain', form.elements.curve_strain.value);
      const response = await fetch(url, {headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Could not load curves. Check that you are signed in, then retry.');
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Could not load the selected curves. Retry or open the source records.');
      const expected = section.dataset.selection.split(',').map(Number);
      if (!Array.isArray(result.records) || result.records.length !== expected.length
          || result.records.some((record, index) => record.pk !== expected[index])) throw new Error('The returned selection changed. Reload this comparison before retrying.');
      payload = result;
      render();
    } catch (error) {
      status.dataset.error = 'true';
      status.textContent = error.name === 'AbortError' ? 'Loading timed out. Retry or open the source records.' : error.message;
      retry.hidden = false;
      section.dataset.loaded = 'error';
    } finally { clearTimeout(timeout); loading = false; controller = null; }
  }

  section.addEventListener('toggle', () => { if (section.open) load(); });
  retry.addEventListener('click', load);
  clearFocus.addEventListener('click', () => selectRecord(null));
  separate.addEventListener('click', () => {
    separateView.hidden = false; overlayView.hidden = true;
    scaleNote.textContent = 'Each panel uses its own scale.';
    separate.setAttribute('aria-pressed', 'true'); overlay.setAttribute('aria-pressed', 'false');
    for (const plot of plots) plot.resize();
  });
  overlay.addEventListener('click', () => {
    if (!payload || !StudyCurves.canOverlay(payload)) return;
    separateView.hidden = true; overlayView.hidden = false;
    scaleNote.textContent = 'All curves use the same axes and scale.';
    separate.setAttribute('aria-pressed', 'false'); overlay.setAttribute('aria-pressed', 'true');
    for (const plot of plots) plot.resize();
  });
  window.addEventListener('pagehide', () => controller?.abort());
  if (section.open) load();
})();
