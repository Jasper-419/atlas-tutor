"""Pure evidence-aware ranking metrics and a small isolated facade benchmark.

This evaluates exact source/quote matches, not semantic equivalence or generated
answers. The fixture provider is deterministic and is never a model-quality claim.
"""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def _gold_key(item):
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def ranking_metrics(citations, gold, k=6):
    """Each gold evidence is credited once; repeated chunks provide zero gain.

    gold items constrain source_id plus optional version/chunk_index/page/quote.
    nDCG uses one binary gain per rank with fresh evidence. Precision divides by
    the returned window length; MRR/MAP/Recall all share the same exact matcher.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError('k must be positive')
    unique = {_gold_key(item): item for item in gold}
    gold = list(unique.values())
    if any(not isinstance(item, dict) or not item.get('source_id') for item in gold):
        raise ValueError('gold requires source_id')
    seen, gains, fresh_counts = set(), [], []
    for ref in citations[:k]:
        matched = set()
        for index, item in enumerate(gold):
            if ref.get('source_id') != item['source_id']:
                continue
            if 'source_version' in item and ref.get('source_version') != item['source_version']:
                continue
            if 'chunk_index' in item and item['chunk_index'] not in ref.get('chunk_indices', [ref.get('chunk_index')]):
                continue
            if 'page' in item and not (ref.get('page_start') is not None and ref['page_start'] <= item['page'] <= (ref.get('page_end') or ref['page_start'])):
                continue
            if 'quote' in item and (not isinstance(item['quote'], str) or not item['quote'].strip() or item['quote'] not in ref.get('excerpt', '')):
                continue
            matched.add(index)
        fresh = matched - seen
        gains.append(int(bool(fresh)))
        fresh_counts.append(len(fresh))
        seen.update(matched)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(gold)) + 1))
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
    cumulative, average_precision = 0, 0
    for rank, fresh_count in enumerate(fresh_counts, 1):
        cumulative += fresh_count
        if fresh_count:
            average_precision += cumulative / rank
    return {'recall': len(seen) / len(gold) if gold else 0.0,
            'precision': sum(gains) / len(gains) if gains else 0.0,
            'ndcg': min(1.0, dcg / ideal) if ideal else 0.0,
            'mrr': next((1 / rank for rank, gain in enumerate(gains, 1) if gain), 0.0),
            'average_precision': min(1.0, average_precision / len(gold)) if gold else 0.0,
            'hit': float(bool(seen)), 'gold_count': len(gold), 'matched_count': len(seen)}


DATASET = {
    'sources': [
        {'id': 'release', 'title': '发布说明', 'content': '版本 2.6.8 修复了文档索引失败，并保留旧版原文。'},
        {'id': 'numbers', 'title': '独立数字', 'content': '数字 2、6、8 表示三个独立编号，与版本号无关。'},
        {'id': 'entropy', 'title': '信息论', 'content': '熵衡量信息的不确定性。平均信息量越大，熵越大。'},
        {'id': 'variables', 'title': '变量定义', 'content': '变量 x 表示模型输入，y 表示预测输出。'},
        {'id': 'gradient', 'title': '梯度下降', 'content': '梯度下降沿目标函数梯度的反方向更新参数以减小损失。'},
        {'id': 'gradient-copy', 'title': '重复资料', 'content': '梯度下降沿目标函数梯度的反方向更新参数以减小损失。'},
        {'id': 'private', 'title': '他人资料', 'content': '秘密口令：只属于另一个用户。', 'user_id': 2, 'course_id': 'other'},
    ],
    'cases': [
        {'id': 'dotted-identifier', 'query': '2.6.8', 'gold': [{'source_id': 'release', 'quote': '版本 2.6.8'}]},
        {'id': 'single-han', 'query': '熵', 'gold': [{'source_id': 'entropy', 'quote': '不确定性'}]},
        {'id': 'single-latin', 'query': 'x', 'gold': [{'source_id': 'variables', 'quote': 'x 表示模型输入'}]},
        {'id': 'direct-question', 'query': '梯度下降怎样更新参数', 'gold': [{'source_id': 'gradient', 'quote': '梯度的反方向'}]},
        {'id': 'context-reference', 'query': '它衡量什么', 'history': [{'role': 'user', 'content': '我正在学习信息论中的熵'}],
         'gold': [{'source_id': 'entropy', 'quote': '熵衡量信息的不确定性'}]},
        {'id': 'filtered-source', 'query': '模型输入', 'source_ids': ['variables'], 'gold': [{'source_id': 'variables'}]},
    ],
}


async def evaluate(db, dataset, *, mode='lexical', k=6):
    from backend.retrieval_agent import retrieve
    cases = []
    for case in dataset['cases']:
        try:
            result = await retrieve(db, 1, 'fixture', case['query'], history=case.get('history'),
                source_ids=case.get('source_ids'), source_kinds=case.get('source_kinds'),
                mode='lexical' if mode == 'lexical' else 'enhanced', limit=k)
            item = {'id': case['id'], 'query': case['query'], 'status': 'scored',
                    'metrics': ranking_metrics(result['citations'], case['gold'], k),
                    'retrieval': result['retrieval'], 'citations': result['citations']}
            # Model failures are explicit and excluded from enhanced score means.
            if mode != 'lexical' and any(result['retrieval'][stage]['status'] == 'fallback' for stage in ['rewrite', 'rerank']):
                item['status'] = 'degraded'
            cases.append(item)
        except Exception as exc:
            # Do not persist arbitrary provider messages, URLs, or credentials.
            cases.append({'id': case['id'], 'query': case['query'], 'status': 'failed', 'error_type': type(exc).__name__})
    scored = [case['metrics'] for case in cases if case['status'] == 'scored']
    means = {key: sum(item[key] for item in scored) / len(scored) if scored else None
             for key in ['recall', 'precision', 'ndcg', 'mrr', 'average_precision', 'hit']}
    return {'version': 1, 'path': 'backend.retrieval_agent.retrieve', 'mode': mode,
            'model_responses': 'deterministic_fixture' if mode == 'fixture' else ('live_provider' if mode == 'live' else 'none'),
            'scope': 'isolated_synthetic_corpus', 'matching': 'exact_source_and_optional_quote_or_locator',
            'limitations': 'Small synthetic cases only; no semantic judge, answer quality, or general improvement claim.',
            'k': k, 'counts': {status: sum(case['status'] == status for case in cases) for status in ['scored', 'degraded', 'failed']},
            'means': means, 'cases': cases}


async def _fixture_completion(messages, user_id, step, **kwargs):
    data = json.loads(messages[-1]['content'])
    if step == 'retrieval_rewrite':
        return {'query': data['query'] + ' ' + data['context'][-1]['content']}
    # A deterministic fixture only validates the contract; it does not simulate intelligence.
    return {'ranking': [{'id': ref['id'], 'quote': ref['excerpt'][:80]} for ref in data['candidates']]}


async def _isolated_run(args):
    # Must happen before backend imports; .env's non-overriding load cannot redirect this.
    with tempfile.TemporaryDirectory(prefix='atlas-retrieval-eval-') as temp:
        os.environ['DATABASE_URL'] = 'sqlite:///' + temp + '/evaluation.db'
        os.environ['ATLAS_DATA_DIR'] = temp
        from backend.database import Base, engine, SessionLocal
        from backend.models import User, Course
        from backend.retrieval import add_source, split_text
        if str(engine.url) != os.environ['DATABASE_URL']:
            raise RuntimeError('Evaluation requires a fresh process with its isolated database')
        dataset = json.loads(Path(args.dataset).read_text()) if args.dataset else DATASET
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add_all([User(id=1, email='retrieval@fixture.invalid', hashed_password='fixture'),
                        User(id=2, email='other@fixture.invalid', hashed_password='fixture')])
            db.flush()
            db.add_all([Course(id='fixture', user_id=1, title='评估课程', goal='隔离检索'),
                        Course(id='other', user_id=2, title='他人课程', goal='范围检查')])
            db.flush()
            for item in dataset['sources']:
                await add_source(db, item.get('user_id', 1), item.get('course_id', 'fixture'),
                    item['title'], item['content'], source_id=item['id'], kind=item.get('kind', 'text'),
                    prepared=(split_text(item['content']), []))
            db.commit()
            if args.mode == 'fixture':
                with patch('backend.retrieval_agent.complete', _fixture_completion):
                    return await evaluate(db, dataset, mode=args.mode, k=args.k)
            return await evaluate(db, dataset, mode=args.mode, k=args.k)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['lexical', 'fixture', 'live'], default='lexical')
    parser.add_argument('--dataset', help='Optional JSON with sources and cases; always loaded into temporary DB')
    parser.add_argument('--k', type=int, default=6)
    parser.add_argument('--output', help='Write a reproducible JSON report to this path')
    args = parser.parse_args(argv)
    if not 1 <= args.k <= 20:
        parser.error('--k must be between 1 and 20')
    report = asyncio.run(_isolated_run(args))
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'}, ensure_ascii=False, indent=2))
    return 1 if report['counts']['failed'] or report['counts']['degraded'] else 0
