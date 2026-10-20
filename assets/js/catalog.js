/* домщенков.рф — каталог /shchenki/: все щенки одной сеткой, без фильтров (клиент 19.10).
   Плитка «Ждёте другого щенка?» [data-cf-more] дополняет последний ряд сетки [data-cf-list]; если ряд полный —
   встаёт отдельной строкой. Старые ссылки с ?breed=… открывают весь каталог. */
(() => {
  'use strict';

  const root = document.querySelector('[data-catalog]');
  if (!root) return;
  const list = root.querySelector('[data-cf-list]');
  const more = root.querySelector('[data-cf-more]');
  if (!list || !more) return;
  const count = list.querySelectorAll(':scope > li[data-breed]').length;

  const fitMore = () => {
    const cs = getComputedStyle(list);
    const cols = cs.display === 'grid' ? cs.gridTemplateColumns.split(' ').filter(Boolean).length || 1 : 1;
    const rest = count % cols;
    more.style.gridColumn = 'span ' + (rest ? cols - rest : cols);
    more.classList.toggle('is-shared', rest > 0); // делит ряд с карточками → колонкой (pages.css)
  };

  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(fitMore, 120); });
  fitMore();
})();
