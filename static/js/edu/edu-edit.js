(function () {
  'use strict';
  var Speech = window.Edu.Speech;
  var Store = window.Edu.Store;
  var Kids = window.Edu.Kids;
  var Nav = window.Edu.Nav;

  var editKidId = null;
  var editKidAva = '🧒';

  window.Edu.Edit = {
    editKidId: editKidId,
    editKidAva: editKidAva
  };

  window.homeEditKid = function (id) {
    var kids = window.eduKids ? window.eduKids.list() : [];
    var k = kids.find(function(x){ return x.id === id; });
    if (!k) return;
    editKidId = id;
    editKidAva = k.avatar || '🧒';
    document.getElementById('editNameInput').value = k.name;
    var ysel = document.getElementById('editYearInput');
    if (ysel) ysel.value = k.birthYear;
    document.querySelectorAll('#editAvaPick button').forEach(function(b){ b.classList.toggle('active', b.dataset.a === editKidAva); });
    document.getElementById('kidDelBtn').style.display = '';
    document.getElementById('eduMaskKidEdit').style.display = 'flex';
  };

  window.pickEditAva = function (a) {
    editKidAva = a;
    document.querySelectorAll('#editAvaPick button').forEach(function(b){ b.classList.toggle('active', b.dataset.a === a); });
  };

  window.kidEditSave = function () {
    var name = document.getElementById('editNameInput').value.trim();
    var year = parseInt(document.getElementById('editYearInput').value, 10);
    if (!name || !year) { Speech.toast('请填写完整'); return; }
    var data = { kids: [{ dbId: editKidId, name: name, birthYear: year, gender: (k && k.gender) || 'male', avatar: editKidAva }], removedIds: [] };
    var kids = window.eduKids ? window.eduKids.list() : [];
    var k = kids.find(function(x){ return x.id === editKidId; });
    fetch('/edu/api/kids', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) })
      .then(function(r){ return r.json(); })
      .then(function(res){
        if (res.ok) {
          document.getElementById('eduMaskKidEdit').style.display = 'none';
          Nav.renderHome();
        } else { Speech.toast(res.error || '保存失败'); }
      })
      .catch(function(){ Speech.toast('网络异常，保存失败'); });
  };

  window.openKidsMgr = function () {
    var list = document.getElementById('kidsMgrList');
    var kids = window.eduKids ? window.eduKids.list() : [];
    list.innerHTML = kids.map(function(k){
      return '<div class="kid-mgr-item" style="display:flex;align-items:center;gap:10px;padding:10px;border-bottom:1px solid var(--edu-border-2);">'+
        '<span style="font-size:1.5rem;">'+(k.avatar||'🧒')+'</span>'+
        '<div class="kid-mgr-info" style="flex:1;"><div>'+k.name+'</div><div style="font-size:.8rem;color:var(--edu-muted);">'+k.birthYear+'年生 · '+(k.gender==='male'?'男':'女')+'</div></div>'+
        '<button type="button" class="btn-soft" style="font-size:.75rem;padding:4px 10px;" onclick="window.Edu.KidsMgr.mgrDeleteKid(\''+k.id+'\')">删除</button>'+
        '</div>';
    }).join('');
    document.getElementById('eduMaskKidsMgr').style.display = 'flex';
  };

  window.Edu.KidsMgr = {
    openKidsMgr: window.openKidsMgr
  };

  window.Edu.KidsMgr.mgrDeleteKid = function (id) {
    window.requireParent(function(){
      fetch('/edu/api/kids', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ kids:[], removedIds:[id] }) })
        .then(function(r){ return r.json(); })
        .then(function(res){
          if (res.ok) { window.openKidsMgr(); Nav.renderHome(); }
          else { Speech.toast(res.error || '删除失败'); }
        })
        .catch(function(){ Speech.toast('网络异常，删除失败'); });
    });
  };
})();