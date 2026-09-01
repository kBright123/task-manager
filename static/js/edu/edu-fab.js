(function () {
  'use strict';

  function quickFabSet(show) {
    var f = document.getElementById('quickFab');
    if (f) f.style.display = show ? '' : 'none';
  }

  window.Edu.FAB = {
    quickFabSet: quickFabSet
  };
})();