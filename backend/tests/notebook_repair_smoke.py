"""Isolated notes/repair service smoke; only external completions are fixtures.

Run: .venv-atlas/bin/python -m backend.tests.notebook_repair_smoke
Uses a temporary SQLite database and disables dotenv before backend imports.
"""

import os, tempfile, asyncio, copy, json
from pathlib import Path
from unittest.mock import patch
folder=tempfile.TemporaryDirectory(prefix='atlas-core2-notes-')
os.environ.update(PYTHON_DOTENV_DISABLED='1',ATLAS_DATA_DIR=folder.name,DATABASE_URL='sqlite:///'+str(Path(folder.name)/'smoke.db'),WORKER_MODE='disabled',EMBEDDING_MODEL='')
from fastapi import HTTPException
from backend.database import Base,engine,SessionLocal
from backend.models.domain import User,Course,Node,Source,Exercise,Attempt,Review,Memory
from backend.models.learning import LearningEvidence,NodeLearningState,ExerciseMetadata
from backend.models.tutor import TutorSession,TutorTurn
from backend.models.notebook import NotebookNote,ExerciseCorrection
from backend.models.teaching import MisconceptionReview,PracticeTarget
from backend.llm import ModelError
from backend import notes,assessment_repair as repair
Base.metadata.create_all(engine)
def denied(status,func,*args,**kw):
    try: func(*args,**kw)
    except HTTPException as e: assert e.status_code==status,(e.status_code,e.detail)
    else: raise AssertionError('operation should be denied')
async def async_denied(status,func,*args,**kw):
    try: await func(*args,**kw)
    except HTTPException as e: assert e.status_code==status,(e.status_code,e.detail)
    else: raise AssertionError('operation should be denied')
with SessionLocal() as db:
    db.add_all([User(id=1,email='one@smoke',hashed_password='x'),User(id=2,email='two@smoke',hashed_password='x')]);db.flush()
    db.add_all([Course(id='course',user_id=1,title='Course',goal='Goal',status='active'),Course(id='foreign',user_id=2,title='Private',goal='Goal'),Course(id='other',user_id=1,title='Other',goal='Goal')]);db.flush()
    db.add_all([Node(id='node',user_id=1,course_id='course',title='Node',objective='Define the concept',status='learning',mastery=70),Source(id='source',user_id=1,course_id='course',title='Owned source'),Source(id='secret',user_id=2,course_id='foreign',title='Secret')]);db.commit()
    # Cancellation/outer rollback must undo service writes.
    temporary=notes.create_note(db,1,'Rollback','must vanish',request_id='rollback')
    db.rollback()
    assert db.query(NotebookNote).filter_by(id=temporary['id']).first() is None,'notes service committed before caller'
    note=notes.create_note(db,1,'My note','Own understanding',course_id='course',source_ids=['source'],request_id='note-one');db.commit()
    assert notes.create_note(db,1,'My note','Own understanding',course_id='course',source_ids=['source'],request_id='note-one')['id']==note['id']
    db.get(Source,'source').version += 1;db.commit()
    assert notes.create_note(db,1,'My note','Own understanding',course_id='course',source_ids=['source'],request_id='note-one')['id']==note['id']
    denied(409,notes.create_note,db,1,'Changed','Own understanding',request_id='note-one')
    denied(404,notes.get_note,db,2,note['id'])
    denied(404,notes.create_note,db,1,'Leak','No',source_ids=['secret'])
    denied(404,notes.create_note,db,1,'Wrong course','No',course_id='other',source_ids=['source'])
    updated=notes.update_note(db,1,note['id'],1,content='Edited understanding');db.commit();assert updated['version']==2
    denied(409,notes.update_note,db,1,note['id'],1,content='stale')
    filename,markdown=notes.export_note(db,1,note['id']);assert filename.endswith('.md') and 'Edited understanding' in markdown and 'Owned source' in markdown
    db.add(TutorSession(id='session',user_id=1,course_id='course',title='Session'));db.flush()
    db.add(TutorTurn(id='turn',user_id=1,session_id='session',request_id='turn-1',status='completed',input='Never save this input',output='Server completed answer',checkpoint={'citations':[{'source_id':'source','title':'Owned source','quote':'actual server quote'}]}));db.commit()
    saved=notes.save_from_turn(db,1,'turn');db.commit();assert saved['content']=='Server completed answer' and saved['sources'][0]['quote']=='actual server quote'
    assert notes.save_from_turn(db,1,'turn')['id']==saved['id'];assert len(notes.list_notes(db,1,'course'))==2
    print('PASS notes: ownership, source scope, rollback, idempotency, optimistic edit, server turn, export')
async def model(messages,user_id,step,**kwargs):
    payload=json.loads(messages[-1]['content'])
    if step=='question_repair_preview':
        if 'void' in payload['reason']: return {'mode':'void','reason':'Question ambiguous'}
        return {'mode':'correct','reason':'Key incorrect','correct_answer':'B body' if payload['question']['type']=='choice' else 'Correct open reference','rubric':'Accuracy 60, reasoning 25, clarity 15','explanation':'The material supports the corrected relation.'}
    if step=='question_repair_grading_preview':
        return {'assessments':[{'attempt_id':a['attempt_id'],'criteria_scores':[{'id':'correctness','score':60},{'id':'reasoning','score':25},{'id':'clarity','score':15}],'feedback':'Correct using all three criteria.','misconception':''} for a in payload['attempts']]}
    raise AssertionError(step)
async def main():
  with SessionLocal() as db:
    db.add(NodeLearningState(user_id=1,node_id='node',baseline_mastery=80,strategy='concept'))
    db.add_all([Exercise(id='choice',user_id=1,node_id='node',type='choice',prompt='Select the relation',options=['A body','B body'],correct_answer='A body',explanation='Original key'),Exercise(id='unanswered',user_id=1,node_id='node',type='open',prompt='Unanswered',options=[],correct_answer='SECRET_UNANSWERED_KEY',explanation='Hidden'),Exercise(id='open',user_id=1,node_id='node',type='open',prompt='Explain relation',options=[],correct_answer='Old reference')]);db.flush()
    db.add(Attempt(id='attempt',user_id=1,exercise_id='choice',node_id='node',request_id='answer1',answer='B',score=0,feedback='Original wrong grade',correct_answer='A body',mastery=60,passed=False));db.flush()
    db.add(LearningEvidence(user_id=1,attempt_id='attempt',exercise_id='choice',node_id='node',skill_type='concept',difficulty='beginner',score=0,independent=True,misconception='Original misconception'))
    db.add(Attempt(id='open-attempt',user_id=1,exercise_id='open',node_id='node',request_id='answer-open',answer='Original open answer stays unchanged',score=40,feedback='Original open grade',correct_answer='Old reference',mastery=60,passed=False));db.flush()
    db.add(LearningEvidence(user_id=1,attempt_id='open-attempt',exercise_id='open',node_id='node',skill_type='concept',difficulty='beginner',score=40,independent=True,misconception='Original open misconception'));db.commit()
    db.add(Memory(user_id=1,course_id='course',category='misconception',content='[exercise:choice] Original legacy diagnosis'));db.commit()
    with patch.object(repair,'complete',model):
      discarded=await repair.propose_repair(db,1,'choice','bad key','discarded');db.rollback()
      assert not db.query(ExerciseCorrection).filter_by(action_id='discarded').first(),'proposal committed before caller'
      p=await repair.propose_repair(db,1,'choice','bad key','repair-choice');db.commit()
      assert p['mode']=='correct' and any(c['path']=='第1次作答评分' and c['after']['score']==100 for c in p['changes'])
      assert db.get(Attempt,'attempt').score==0,'proposal directly changed score'
      assert (await repair.propose_repair(db,1,'choice','bad key','repair-choice'))==p
      await async_denied(404,repair.apply_repair,db,2,p)
      changed=copy.deepcopy(p);changed['new_contract']['correct_answer']='A body';await async_denied(409,repair.apply_repair,db,1,changed)
      result=await repair.apply_repair(db,1,p);db.rollback();assert db.get(Attempt,'attempt').score==0,'repair apply committed'
      result=await repair.apply_repair(db,1,p);db.commit();assert result['attempts'][0]['score']==100 and db.get(Attempt,'attempt').answer=='B'
      assert await repair.apply_repair(db,1,p)==result
      assert db.query(LearningEvidence).filter_by(attempt_id='attempt').one().independent
      assert db.query(NodeLearningState).filter_by(node_id='node').one().baseline_mastery==80
      assert db.query(Memory).filter(Memory.content.startswith('[exercise:choice]')).one().category=='invalidated_assessment','legacy diagnosis remained active after correction'
      audit=db.query(ExerciseCorrection).filter_by(action_id='repair-choice').one();assert audit.before_snapshot['attempts'][0]['score']==0 and audit.after_snapshot['attempts'][0]['score']==100
      op=await repair.propose_repair(db,1,'open','bad rubric','repair-open');db.commit();assert op['regrades'][0]['score']==100
      async def no_model(*a,**k): raise AssertionError('confirmation must not generate another grade')
      with patch.object(repair,'complete',no_model): await repair.apply_repair(db,1,op)
      db.commit();assert db.get(Attempt,'open-attempt').answer=='Original open answer stays unchanged' and db.get(Attempt,'open-attempt').score==100
      up=await repair.propose_repair(db,1,'unanswered','void ambiguity','repair-unanswered');db.commit()
      assert 'SECRET_UNANSWERED_KEY' not in json.dumps({k:up[k] for k in ('title','changes')})
      await repair.apply_repair(db,1,up);db.commit();assert db.get(Exercise,'unanswered').voided
      changed_question=await repair.propose_repair(db,1,'choice','void changed question','repair-revision');db.commit()
      db.get(Exercise,'choice').revision += 1;db.commit()
      await async_denied(409,repair.apply_repair,db,1,changed_question)
      stale=await repair.propose_repair(db,1,'choice','void ambiguous','repair-stale');db.commit()
      db.add(Attempt(user_id=1,exercise_id='choice',node_id='node',request_id='late',answer='A',score=0,feedback='late',correct_answer='B body',mastery=60,passed=False));db.commit()
      await async_denied(409,repair.apply_repair,db,1,stale)
      vp=await repair.propose_repair(db,1,'choice','void ambiguous','repair-void');db.commit()
      await repair.apply_repair(db,1,vp);db.commit()
      assert all(a.voided for a in db.query(Attempt).filter_by(exercise_id='choice'))
      ev=db.query(LearningEvidence).filter_by(attempt_id='attempt').one();assert not ev.independent and not ev.misconception
      assert db.query(NodeLearningState).filter_by(node_id='node').one().baseline_mastery==80
      assert db.query(ExerciseCorrection).filter_by(status='applied').count()==4
      assert db.query(LearningEvidence).count()==2,'repair fabricated independent evidence'
      print('PASS repairs: private previews, exact open regrade, no confirmation model, ownership, stale snapshot, caller rollback, audit, baseline, void evidence, replay')
    # Repairing an already successful transfer answer must replace, rather than
    # discard or blindly copy, its semantic evidence for the linked diagnosis.
    db.add(Node(id='target-node',user_id=1,course_id='course',title='Transfer',objective='Distinguish examples from definitions',status='learning',mastery=55));db.flush()
    db.add_all([
        Exercise(id='origin',user_id=1,node_id='target-node',type='open',prompt='Define the concept',correct_answer='Definition includes constraints',created_at='2025-01-01T00:00:00+00:00'),
        Exercise(id='transfer',user_id=1,node_id='target-node',type='open',prompt='Explain why a new example does not establish a definition',correct_answer='The example is an instance',created_at='2025-01-03T00:00:00+00:00'),
    ]);db.flush()
    db.add_all([
        Attempt(id='origin-answer',user_id=1,exercise_id='origin',node_id='target-node',request_id='origin-answer',answer='An example is the definition',score=40,feedback='Mistakes an instance for a universal definition',correct_answer='Definition includes constraints',mastery=40,passed=False,created_at='2025-01-01T01:00:00+00:00'),
        Attempt(id='transfer-answer',user_id=1,exercise_id='transfer',node_id='target-node',request_id='transfer-answer',answer='This instance shows one case; a definition must specify the necessary constraints in every applicable case.',score=100,feedback='Demonstrates the distinction',correct_answer='The example is an instance',mastery=55,passed=True,created_at='2025-01-03T01:00:00+00:00'),
    ]);db.flush()
    db.add_all([
        LearningEvidence(user_id=1,attempt_id='origin-answer',exercise_id='origin',node_id='target-node',skill_type='concept',difficulty='beginner',score=40,independent=True,misconception='Treats one example as a universal definition'),
        LearningEvidence(user_id=1,attempt_id='transfer-answer',exercise_id='transfer',node_id='target-node',skill_type='concept',difficulty='beginner',score=100,independent=True,misconception='',criteria_scores=[{'id':'correctness','score':60,'max_points':60,'target_checks':[{'misconception_id':'target-review','demonstrates_understanding':True,'reason':'OLD semantic proof, must not be copied'}]}]),
        MisconceptionReview(id='target-review',user_id=1,node_id='target-node',origin_exercise_id='origin',origin_attempt_id='origin-answer',description='Treats one example as a universal definition',status='resolved',resolved_attempt_id='transfer-answer',resolved_at='2025-01-03T01:00:00+00:00',created_at='2025-01-02T00:00:00+00:00'),
    ]);db.flush()
    db.add(PracticeTarget(user_id=1,exercise_id='transfer',misconception_id='target-review'));db.commit()
    grading_payloads=[]
    semantic_understanding=True
    async def transfer_model(messages,user_id,step,**kwargs):
        result=await model(messages,user_id,step,**kwargs)
        if step=='question_repair_grading_preview':
            grading_payloads.append(json.loads(messages[-1]['content']))
            for grade in result['assessments']:
                grade['target_checks']=[{'misconception_id':'target-review','demonstrates_understanding':semantic_understanding,'reason':'Fresh check: the answer distinguishes one instance from necessary constraints in every applicable case.' if semantic_understanding else 'Fresh check: the revised task requires an additional causal link that this answer does not explain.'}]
        return result
    with patch.object(repair,'complete',transfer_model):
        transfer_preview=await repair.propose_repair(db,1,'transfer','review revised rubric','target-repair');db.commit()
    with patch.object(repair,'complete',no_model):
        await repair.apply_repair(db,1,transfer_preview);db.commit()
    assert db.get(MisconceptionReview,'target-review').status=='resolved','successful repaired transfer answer lost its semantic resolution evidence'
    assert grading_payloads[0]['target_misconceptions']==[{'id':'target-review','description':'Treats one example as a universal definition'}]
    checks=db.query(LearningEvidence).filter_by(attempt_id='transfer-answer').one().criteria_scores[0]['target_checks']
    assert checks[0]['reason'].startswith('Fresh check:'),'repair reused stale semantic checks'
    async def unrelated_target_model(messages,user_id,step,**kwargs):
        result=await transfer_model(messages,user_id,step,**kwargs)
        if step=='question_repair_grading_preview':
            result['assessments'][0]['target_checks'][0]['misconception_id']='unrelated-target'
        return result
    with patch.object(repair,'complete',unrelated_target_model):
        try: await repair.propose_repair(db,1,'transfer','review unrelated target','invalid-target-repair')
        except ModelError: pass
        else: raise AssertionError('unrelated semantic checks were accepted')
    assert not db.query(ExerciseCorrection).filter_by(action_id='invalid-target-repair').first()
    semantic_understanding=False
    with patch.object(repair,'complete',transfer_model):
        negative_preview=await repair.propose_repair(db,1,'transfer','review additional reasoning','negative-target-repair');db.commit()
    assert negative_preview['regrades'][0]['score']==100
    with patch.object(repair,'complete',no_model):
        await repair.apply_repair(db,1,negative_preview);db.commit()
    assert db.get(MisconceptionReview,'target-review').status=='open','high total score overrode a negative fresh semantic check'
    checks=db.query(LearningEvidence).filter_by(attempt_id='transfer-answer').one().criteria_scores[0]['target_checks']
    assert checks[0]['demonstrates_understanding'] is False,'old positive semantic check survived replacement'
    print('PASS target repair: fresh positive/negative checks preserve or reopen resolution independently of total score; unrelated target rejected; confirmation calls no model')
asyncio.run(main())
