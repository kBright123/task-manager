# -*- coding: utf-8 -*-
import os
os.environ['KB_VECTOR_DISABLED']='1'; os.environ['KB_LLM_DISABLED']='1'; os.environ['KB_CLASSIFIER_ENABLED']='0'
import sys; sys.path.insert(0,'.')
from app import _parse_time, extract_title_from_text, parse_task_from_text, extract_assignees_from_text
ok=True
def chk(name,cond,extra=''):
    global ok
    print(('PASS ' if cond else 'FAIL ')+name+(' | '+str(extra) if not cond and extra else ''))
    if not cond: ok=False

print('-- ①时间bug修复 --')
chk('6:15保持24h制', _parse_time('6:15开会')==(6,15), _parse_time('6:15开会'))
chk('早上6点半=6:30', _parse_time('早上6点半')==(6,30), _parse_time('早上6点半'))
chk('凌晨1点=1:00', _parse_time('凌晨1点')==(1,0), _parse_time('凌晨1点'))
chk('晚上8点=20:00', _parse_time('晚上8点')==(20,0), _parse_time('晚上8点'))
chk('9点30=9:30', _parse_time('9点30')==(9,30), _parse_time('9点30'))

print('-- ③标题冒号 --')
t1=extract_title_from_text('提醒:明天交周报')
chk('提醒:明天交周报', t1=='明天交周报', t1)
t2=extract_title_from_text('【项目会】下周三2点 开会')
chk('【】优先', t2=='项目会', t2)

print('-- ④⑤⑥综合 --')
r=parse_task_from_text('每天下班前提交日报')
chk('每天→daily', r['recurrence']=='daily' and r['recurrence_interval_days']==1, r['recurrence'])
r=parse_task_from_text('每周三下午2点开项目例会')
chk('每周三→weekly+周三文本', r['recurrence']=='weekly' and r['recurrence_text']=='每周三', (r['recurrence'],r['recurrence_text']))
r=parse_task_from_text('准备考试资料，复习考试大纲，工作安排往后放一放')
chk('分类投票(考试2>工作1)', r['category']=='考试', (r['category'],))
print('-- JioNLP 集成 --')
r=parse_task_from_text('开发登录功能从明天上午9点开始到下周五下午6点结束 发给张三')
chk('start为未来(明天9点)', r['start_time'].hour==9 and r['start_time']>__import__('datetime').datetime.now(), r['start_time'])
r2=parse_task_from_text('随便写点东西')
chk('无时间词回退默认end', r2['end_time'] is not None)

NOTICE='''【关于举办软件研发中心合肥分中心2026年大数据Lambda架构与Kappa架构企业级应用培训班的通知】各位领导、同事：@所有人
      培训时间：2026年8月26日（下周三）14:10-17:00
      培训方式：邮连线上会议（会议号：920230609990）
      如有意向报名，请于8月25日（下周二）12：00前填报在线文档。'''
r=parse_task_from_text(NOTICE)
from datetime import datetime
chk('通知:标题取【】且去"关于/的通知"', r['title'].startswith('举办软件研发中心') or '培训班' in r['title'], r['title'])
chk('通知:分类=培训', r['category']=='培训', r['category'])
chk('通知:@所有人', r['is_all'] is True)
exp_s=datetime(2026,8,26,14,10); exp_e=datetime(2026,8,26,17,0)
chk('通知:start=8/26 14:10', r['start_time'].replace(second=0,microsecond=0)==exp_s, r['start_time'])
chk('通知:end=8/26 17:00', r['end_time'].replace(second=0,microsecond=0)==exp_e, r['end_time'])

print()
print('== 结果:','ALL PASS' if ok else 'FAILED ==')
sys.exit(0 if ok else 1)
