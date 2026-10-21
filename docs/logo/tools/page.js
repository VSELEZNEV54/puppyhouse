(function () {
  var KEY = 'logo-tryon';
  function show(id) {
    var tpl = document.getElementById('tpl-' + id);
    if (!tpl) return;
    document.querySelectorAll('[data-slot-target]').forEach(function (slot) {
      var src = tpl.content.querySelector('[data-slot="' + slot.dataset.slotTarget + '"]');
      if (src) slot.innerHTML = src.innerHTML;
    });
  }
  document.querySelectorAll('input[name="tryon"]').forEach(function (r) {
    r.addEventListener('change', function () {
      show(r.value);
      try { localStorage.setItem(KEY, r.value); } catch (e) {}
    });
  });
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var input = saved && document.getElementById('try-' + saved);
  if (input) { input.checked = true; show(saved); }
})();
