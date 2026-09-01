(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Legacy = window.Edu.Legacy;

  function subjRowsHtml() {
    var subs = ['zh','math','en'];
    return subs.map(function(s){
      var recs = (Store.state.records || []).filter(function(r){ return r.subj === s; });
      var total = recs.length;
      var right = recs.filter(function(r){ return r.ok; }).length;
      var acc = total ? Math.round(right/total*100) : 0;
      var lv = M.stateLevel(s);
      return '<tr><td>'+C.SUBJ_LABEL[s]+'</td><td>'+total+'</td><td>'+right+'</td><td>'+acc+'%</td><td>Lv.'+lv+'</td></tr>';
    }).join('');
  }

  window.openReport = function () {
    var body = document.getElementById('reportBody');
    var active = window.eduKids ? window.eduKids.active() : null;
    if (!active) return;
    var recs = Store.state.records || [];
    var today = new Date().toISOString().slice(0,10);
    var weekAgo = new Date(Date.now() - 6*86400000).toISOString().slice(0,10);
    var thisWeek = recs.filter(function(r){ return r.t >= new Date(weekAgo).getTime(); });
    var total = thisWeek.length;
    var right = thisWeek.filter(function(r){ return r.ok; }).length;
    var streak = 0;
    for (var d=new Date(today); streak<30; d.setDate(d.getDate()-1)) {
      var ds = d.toISOString().slice(0,10);
      var dayRecs = recs.filter(function(r){ return new Date(r.t).toISOString().slice(0,10) === ds; });
      if (dayRecs.length) streak++; else break;
    }
    body.innerHTML = '<div class="report-grid">'+
      '<div class="report-card"><div class="report-label">本周练习</div><div class="report-value">'+total+' 题</div></div>'+
      '<div class="report-card"><div class="report-label">答对数</div><div class="report-value">'+right+' 题</div></div>'+
      '<div class="report-card"><div class="report-label">正确率</div><div class="report-value">'+(total?Math.round(right/total*100):0)+'%</div></div>'+
      '<div class="report-card"><div class="report-label">连续天数</div><div class="report-value">'+streak+' 天</div></div>'+
      '</div>'+
      '<table class="report-table" style="width:100%;border-collapse:collapse;margin-top:16px;font-size:.9rem;">'+
      '<thead><tr style="border-bottom:2px solid var(--edu-border-2);"><th style="text-align:left;padding:8px;">学科</th><th style="text-align:right;padding:8px;">总题数</th><th style="text-align:right;padding:8px;">答对</th><th style="text-align:right;padding:8px;">正确率</th><th style="text-align:right;padding:8px;">难度档</th></tr></thead>'+
      '<tbody>'+subjRowsHtml()+'</tbody></table>'+
      '<div style="text-align:center;margin-top:14px;"><button type="button" class="btn-soft" onclick="window.eduNav(\'stats\')">📊 打开完整家长看板</button></div>';
    document.getElementById('reportTitle').textContent = '学习报告 - ' + active.name;
    document.getElementById('eduMaskReport').style.display = 'flex';
  };

  window.Edu.Report = {
    openReport: window.openReport,
    subjRowsHtml: subjRowsHtml
  };
})();