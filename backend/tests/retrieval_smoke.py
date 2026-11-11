"""Isolated retrieval boundary checks; fixture model responses are explicitly mocked."""
import asyncio
import os
import tempfile
from unittest.mock import patch


async def main():
    with tempfile.TemporaryDirectory(prefix='atlas-retrieval-smoke-') as temp:
        os.environ['DATABASE_URL'] = 'sqlite:///' + temp + '/test.db'
        os.environ['ATLAS_DATA_DIR'] = temp
        from backend.database import Base, engine, SessionLocal
        from backend.models import User, Course, Node, Source, Chunk
        from backend.retrieval import add_source, search
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add_all([User(id=1, email='one@fixture.invalid', hashed_password='fixture'),
                        User(id=2, email='two@fixture.invalid', hashed_password='fixture')])
            db.flush()
            db.add_all([Course(id='c1', user_id=1, title='本课', goal='测试'),
                        Course(id='c2', user_id=1, title='其他课', goal='测试'),
                        Course(id='c3', user_id=2, title='他人课', goal='测试')])
            db.flush()
            async def source(identifier, text, user=1, course='c1', kind='text'):
                return await add_source(db, user, course, identifier, text, kind=kind,
                                        source_id=identifier, prepared=([text], []))
            await source('exact', '版本 2.6.8 修复了稳定性问题和配置问题。')
            await source('noise', '版本 2 与版本 6 和版本 8 的独立对比。2 6 8 2 6 8')
            await source('han', '熵描述了信息不确定性的平均程度。')
            await source('letter', '变量 x 表示输入，变量 y 表示输出。')
            await source('other', '版本 2.6.8 熵 x 其他课资料', course='c2')
            await source('private', '版本 2.6.8 熵 x 他人资料', user=2, course='c3')
            db.commit()
            found = await search(db, 1, 'c1', '2.6.8')
            assert found[0]['source_id'] == 'exact', found
            assert any(x['source_id'] == 'han' for x in await search(db, 1, 'c1', '熵'))
            assert any(x['source_id'] == 'letter' for x in await search(db, 1, 'c1', 'x'))
            from backend.retrieval_agent import retrieve, read_material
            with patch('backend.retrieval_agent.complete', side_effect=AssertionError('auto must skip models')):
                result = await retrieve(db, 1, 'c1', '2.6.8')
                assert result['retrieval']['queries'][0] == {'query': '2.6.8', 'kind': 'original'}
                assert result['citations'][0]['source_id'] == 'exact'
                assert await search(db, 1, 'c1', '2.6.8', source_ids=['other', 'private']) == []
                assert (await retrieve(db, 1, 'c1', '2.6.8', source_ids=[]))['citations'] == []
            from fastapi import HTTPException
            from backend.library import replace_index
            async def rejects(call, status):
                try:
                    value = call()
                    if hasattr(value, '__await__'):
                        await value
                except HTTPException as exc:
                    assert exc.status_code == status, exc
                else:
                    raise AssertionError('Expected rejection')
            for args in [(2, 'c1', 'exact'), (1, 'c2', 'exact'), (1, 'c1', 'private')]:
                await rejects(lambda args=args: read_material(db, *args), 404)
            await rejects(lambda: retrieve(db, 1, 'c1', '它是什么', node_id='unowned'), 404)
            assert all(c['source_id'] == 'exact' for c in (await retrieve(db, 1, 'c1', '2.6.8', source_ids=['exact']))['citations'])
            history = [{'role': 'assistant', 'content': '不要用这条模型推断'},
                       {'role': 'user', 'content': '请解释信息论中的熵'}]
            calls = []
            async def model(messages, user_id, step, **kwargs):
                import json
                calls.append(step)
                payload = json.loads(messages[-1]['content'])
                if step == 'retrieval_rewrite':
                    assert '不要用这条模型推断' not in str(payload)
                    return {'query': '熵 信息论 不确定性'}
                return {'ranking': [{'id': c['id'], 'quote': c['excerpt'][:20]}
                                    for c in reversed(payload['candidates'])]}
            with patch('backend.retrieval_agent.complete', model):
                rewritten = await retrieve(db, 1, 'c1', '它是什么', history=history)
                assert rewritten['retrieval']['rewrite']['status'] == 'succeeded', rewritten
                assert rewritten['retrieval']['queries'][0]['query'] == '它是什么'
                assert len(rewritten['retrieval']['queries']) <= 3
                assert calls.count('retrieval_rewrite') == 1 and len(calls) <= 2
                for ref in rewritten['citations']:
                    assert db.query(Chunk).filter_by(id=ref['id'], source_id=ref['source_id']).first()
            baseline = (await retrieve(db, 1, 'c1', '版本', mode='lexical'))['citations']
            async def forged(messages, user_id, step, **kwargs):
                import json
                candidates = json.loads(messages[-1]['content'])['candidates']
                return {'ranking': [{'id': c['id'], 'quote': '伪造的原文引文'} for c in candidates]}
            with patch('backend.retrieval_agent.complete', forged):
                bad = await retrieve(db, 1, 'c1', '版本', mode='enhanced')
                assert bad['retrieval']['rerank']['status'] == 'fallback'
                assert bad['citations'] == baseline
            with patch('backend.retrieval_agent.complete', side_effect=RuntimeError('fixture provider down')):
                failure = await retrieve(db, 1, 'c1', '它是什么', history=history)
                assert failure['retrieval']['rewrite']['status'] == 'fallback'
                assert failure['retrieval']['rerank']['status'] == 'skipped'
                assert failure['citations'] == []
            # Invalid IDs, duplicate IDs, and embedding dimension drift are visible fallbacks.
            for corrupt in ['unknown', 'duplicate']:
                async def corrupt_ranking(messages, user_id, step, **kwargs):
                    import json
                    candidates = json.loads(messages[-1]['content'])['candidates']
                    rows = [{'id': c['id'], 'quote': c['excerpt'][:12]} for c in candidates]
                    rows[-1]['id'] = 'invented-id' if corrupt == 'unknown' else rows[0]['id']
                    return {'ranking': rows}
                with patch('backend.retrieval_agent.complete', corrupt_ranking):
                    rejected = await retrieve(db, 1, 'c1', '版本', mode='enhanced')
                    assert rejected['retrieval']['rerank']['status'] == 'fallback'
                    assert rejected['citations'] == baseline
            embedded = db.query(Chunk).filter_by(source_id='exact').one()
            embedded.embedding = [1., 0.]
            db.flush()
            from unittest.mock import AsyncMock
            from backend.config import get_settings
            from backend.indexing import embedding_signature
            indexed = db.get(Source, 'exact')
            settings = get_settings()
            with patch.object(settings, 'embedding_model', 'fixture-model-a'), patch.object(settings, 'embedding_key', 'fixture'):
                with patch('backend.retrieval.embeddings', AsyncMock(return_value=[[1., 0.]])) as embed:
                    legacy = await retrieve(db, 1, 'c1', '2.6.8')
                    assert legacy['retrieval']['warnings'] == ['embedding_unverified']
                    assert legacy['citations'][0]['source_id'] == 'exact'
                    embed.assert_not_awaited()
                indexed.embedding_signature = embedding_signature()
                indexed.embedding_dimension = 2
                db.flush()
                with patch.object(settings, 'embedding_model', 'fixture-model-b'), patch('backend.retrieval.embeddings', AsyncMock(return_value=[[1., 0.]])) as embed:
                    drift = await retrieve(db, 1, 'c1', '2.6.8')
                    assert drift['retrieval']['warnings'] == ['embedding_model_changed']
                    assert drift['citations'][0]['source_id'] == 'exact'
                    embed.assert_not_awaited()
                    compatible = db.get(Source, 'noise')
                    compatible.embedding_signature = embedding_signature()
                    compatible.embedding_dimension = 2
                    compatible_chunk = db.query(Chunk).filter_by(source_id='noise').one()
                    compatible_chunk.embedding = [1., 0.]
                    semantic = await retrieve(db, 1, 'c1', 'semanticprobe')
                    assert {item['source_id'] for item in semantic['citations']} == {'noise'}
                    assert semantic['retrieval']['warnings'] == ['embedding_model_changed']
                    compatible.embedding_signature = compatible.embedding_dimension = None
                    compatible_chunk.embedding = None
                with patch('backend.retrieval.embeddings', AsyncMock(return_value=[[1.]])):
                    drift = await retrieve(db, 1, 'c1', '2.6.8')
                    assert 'embedding_dimension_mismatch' in drift['retrieval']['warnings']
                    assert drift['citations'][0]['source_id'] == 'exact'
                with patch('backend.retrieval.embeddings', AsyncMock(return_value=None)):
                    unavailable = await retrieve(db, 1, 'c1', '2.6.8')
                    assert unavailable['retrieval']['warnings'] == ['embedding_unavailable'], unavailable
                    assert unavailable['citations'][0]['source_id'] == 'exact'
                    explicit_lexical = await retrieve(db, 1, 'c1', '2.6.8', mode='lexical')
                    assert explicit_lexical['retrieval']['warnings'] == []
            indexed.embedding_signature = indexed.embedding_dimension = None
            embedded.embedding = None
            db.flush()
            with patch('backend.retrieval.embeddings', side_effect=AssertionError('No vectors: no provider call')):
                plain = await retrieve(db, 1, 'c1', '2.6.8')
                assert plain['retrieval']['warnings'] == []

            # SQL narrowing must find an older identifier outside the recent chunk cap.
            pieces = ['旧版精确编号 needle-ident.2.6.8 的资料。'] + [f'最新的无关文档片段第{i}项。' for i in range(110)]
            await add_source(db, 1, 'c1', '大库', '\n'.join(pieces), source_id='large', prepared=(pieces, []))
            db.flush()
            bounded_search = await search(db, 1, 'c1', 'needle-ident.2.6.8', candidate_limit=100)
            assert bounded_search and bounded_search[0]['source_id'] == 'large' and bounded_search[0]['chunk_index'] == 0
            # Immutable versions must never use the mutable index or new page map.
            old_text = '[第 1 页]\n第一版的第一页。\n[第 2 页]\n第一版第二页的真实证据。'
            src = await source('versioned', old_text)
            db.flush()
            new_text = '[第 1 页]\n第二版已修改第一页，旧版仍需可读。'
            replace_index(db, src, new_text, ([new_text], []), title='新标题')
            db.commit()
            old = read_material(db, 1, 'c1', 'versioned', version=1, page=2)
            assert old['content'] == '第一版第二页的真实证据。'
            assert old['source']['title'] == 'versioned' and old['source']['current_version'] == 2
            assert old['citations'][0]['page_start'] == old['citations'][0]['page_end'] == 2
            assert old['citations'][0]['source_version'] == 1
            assert read_material(db, 1, 'c1', 'versioned', version=1)['content'] == old_text
            bounded = read_material(db, 1, 'c1', 'versioned', version=1, max_chars=12)
            assert bounded['truncated'] and len(bounded['content']) == 12
            assert bounded['citations'][0]['page_end'] == 1
            await rejects(lambda: read_material(db, 1, 'c1', 'versioned', version=2, page=2), 422)
            await rejects(lambda: read_material(db, 1, 'c1', 'versioned', version=99), 404)
            await rejects(lambda: read_material(db, 1, 'c1', 'versioned', chunk_indices=[99]), 422)
            await rejects(lambda: read_material(db, 1, 'c1', 'versioned', page=1, chunk_indices=[0]), 422)
            await rejects(lambda: read_material(db, 1, 'c1', 'versioned', max_chars=True), 422)
            # Duplicate evidence cannot score twice, even with another result ID.
            from backend.retrieval_evaluation import ranking_metrics
            ranked = [{'source_id': 'one', 'source_version': 1, 'chunk_indices': [0]},
                      {'source_id': 'one', 'source_version': 1, 'chunk_indices': [0]},
                      {'source_id': 'two', 'source_version': 1, 'chunk_indices': [0]}]
            scores = ranking_metrics(ranked, [{'source_id': 'one'}, {'source_id': 'two'}], 2)
            assert scores['recall'] == .5 and scores['precision'] == .5 and scores['mrr'] == 1, scores
            assert 0 <= scores['ndcg'] <= 1
            print('retrieval smoke: passed (identifiers, single chars, scopes, model bounds/fallback, immutable pages, duplicate metrics)')


if __name__ == '__main__':
    asyncio.run(main())
