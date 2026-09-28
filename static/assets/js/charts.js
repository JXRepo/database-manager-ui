(() => {
  const page = document.querySelector('.charts-page');
  if (!page) return;
  page.querySelectorAll('form[data-auto-submit]').forEach(form => {
    form.addEventListener('change', () => form.requestSubmit());
  });
  page.classList.add('charts-js');

  if (window.location.hash === '#objects') {
    const summary = document.getElementById('objects');
    const details = summary?.closest('details');
    if (details) {
      details.open = true;
      summary.scrollIntoView({block: 'start'});
    }
  }

  const plot = document.getElementById('response-plot');
  const source = document.getElementById('curve-points');
  if (!plot || !source) return;
  const points = JSON.parse(source.textContent);
  const tooltip = document.getElementById('curve-tooltip');
  const focus = document.getElementById('curve-focus');
  const guide = document.getElementById('curve-guide');
  const dot = document.getElementById('curve-dot');
  let selected = 0;

  function inspect(index) {
    selected = index;
    const point = points[index];
    focus.removeAttribute('hidden');
    guide.setAttribute('x1', point.px);
    guide.setAttribute('x2', point.px);
    dot.setAttribute('cx', point.px);
    dot.setAttribute('cy', point.py);
    tooltip.textContent = `Point ${point.index + 1}\nStrain: ${point.x_text}\nStress: ${point.y_text}`;
    tooltip.hidden = false;
    const frame = plot.parentElement.getBoundingClientRect();
    const position = new DOMPoint(point.px, point.py).matrixTransform(plot.getScreenCTM());
    tooltip.style.left = `${Math.max(4, Math.min(position.x - frame.left + 13, frame.width - tooltip.offsetWidth - 4))}px`;
    tooltip.style.top = `${Math.max(4, position.y - frame.top - tooltip.offsetHeight - 12)}px`;
  }
  function clearInspection() {
    focus.setAttribute('hidden', '');
    tooltip.hidden = true;
  }
  plot.addEventListener('pointermove', event => {
    const position = new DOMPoint(event.clientX, event.clientY).matrixTransform(plot.getScreenCTM().inverse());
    if (position.x < 74 || position.x > 696 || position.y < 28 || position.y > 248) {
      clearInspection();
      return;
    }
    let nearest = 0;
    let distance = Infinity;
    points.forEach((point, index) => {
      const candidate = (point.px - position.x) ** 2 + (point.py - position.y) ** 2;
      if (candidate < distance) {
        nearest = index;
        distance = candidate;
      }
    });
    inspect(nearest);
  });
  plot.addEventListener('pointerleave', clearInspection);
  plot.addEventListener('focus', () => inspect(selected));
  plot.addEventListener('blur', clearInspection);
  plot.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Escape') return clearInspection();
    if (event.key === 'Home') inspect(0);
    else if (event.key === 'End') inspect(points.length - 1);
    else inspect(Math.max(0, Math.min(points.length - 1, selected + (event.key === 'ArrowRight' ? 1 : -1))));
  });

  const download = document.getElementById('download-curve');
  download.hidden = false;
  download.addEventListener('click', () => {
    const copy = plot.cloneNode(true);
    copy.querySelector('#curve-focus')?.remove();
    copy.removeAttribute('tabindex');
    const captions = [page.querySelector('.charts-curve-caption > span'), ...page.querySelectorAll('.charts-curve-notice')];
    captions.forEach((caption, index) => {
      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', '74');
      text.setAttribute('y', String(326 + index * 16));
      text.setAttribute('fill', '#52687c');
      text.setAttribute('font-family', 'Arial, sans-serif');
      text.setAttribute('font-size', '10');
      text.textContent = caption.textContent.trim().replace(/\s+/g, ' ');
      copy.appendChild(text);
    });
    const height = 338 + (captions.length - 1) * 16;
    copy.setAttribute('viewBox', `0 0 720 ${height}`);
    copy.setAttribute('width', '1440');
    copy.setAttribute('height', String(height * 2));
    copy.querySelector('rect').setAttribute('height', String(height));
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], {type: 'image/svg+xml;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'stress-strain.svg';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
