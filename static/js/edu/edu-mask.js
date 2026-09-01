(function () {
  'use strict';
  var Speech = window.Edu.Speech;

  function closeMask(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }
  window.closeMask = closeMask;

  window.Edu.Mask = {
    closeMask: closeMask,
    openMask: function (id, data) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'flex';
    }
  };

  // Global click to close dropdowns
  document.addEventListener('click', function(){
    var drop = document.getElementById('moreMenuDrop');
    if (drop) drop.classList.remove('show');
    var kidDrop = document.getElementById('kidPickDrop');
    if (kidDrop) kidDrop.classList.remove('show');
  });
})();