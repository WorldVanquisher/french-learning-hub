"""FLH-047 recovery additions to the preserved actual-Qdrant runner."""
import json
import sqlite3
from oracles import assert_embedding_delta
from fake_embeddings import text_digest


def run(r, provider, proxy):
    # Register actual current rendering; the reused source-change case may have run.
    for document in r.probe('documents', r.env['DB_PATH']):
        provider.register(document['Text'], 'document')
    provider.register('flh043 query', 'query')
    for windows in ('info', 'query', 'info-info', 'query-info', 'info-query', 'query-query', 'loss-info', 'loss-query'):
        def search(windows=windows):
            before = provider.snapshot()
            result = r.probe('recovery-search-' + windows, r.env['DB_PATH'])
            assert provider.wait_idle()
            after = provider.snapshot()
            # Each probe includes a separate successful follow-up query.
            first = 0 if windows in ('info-info', 'loss-info') else 1
            assert_embedding_delta(before, after, expected_queries=[text_digest('flh043 query')] * (first + 1))
            assert result['first_counters']['embeddings'] == first
            assert result['first_counters']['input_texts'] == first
            assert result['pass']
            result['provider_before'], result['provider_after'] = before, after
            result['verified_inventory'] = r.verify()
            return result
        r.case('recovery-search-' + windows,
               'one total replacement retry, bounded adapter calls, exact embeddings, honest HTTP state, cached repair/follow-up', search)

    routed = dict(r.env, QDRANT_URL=proxy.base)

    def publication():
        inv = r.inventory()
        with sqlite3.connect(r.env['DB_PATH']) as db:
            space = r.cli('status')['state']['space']
            row = db.execute('SELECT published_collection,published_run_id,published_at FROM semantic_index_spaces WHERE space=?', (space,)).fetchone()
            col = row[0]
            physical = db.execute('SELECT * FROM semantic_index_physical_collections WHERE collection=?', (col,)).fetchall()
            manifest = db.execute('SELECT * FROM semantic_index_manifest WHERE collection=? ORDER BY concept_id', (col,)).fetchall()
            cache = db.execute('SELECT * FROM semantic_embedding_cache ORDER BY content_hash,representation,model_id,dimensions').fetchall()
            # Preserve full SQLite/cache bytes in JSON-compatible evidence.
            cache = [[v.hex() if isinstance(v, bytes) else v for v in item] for item in cache]
        return {'published_fields': row, 'physical': physical, 'manifest': manifest,
                'points': inv[space]['points'], 'cache': cache}

    def measured(operation, env=routed):
        before = provider.snapshot()
        result = r.cli(operation, env)
        assert provider.wait_idle()
        after = provider.snapshot()
        assert_embedding_delta(before, after)
        assert result.get('embedded_texts', 0) == 0
        return {'report': result, 'provider_before': before, 'provider_after': after}

    def create_retired():
        old = r.cli('status')['state']['published_collection']
        proxy.delete_failures.add(old)
        result = measured('rebuild')
        status = r.cli('status')
        assert result['report']['published']
        assert old in result['report']['cleanup_pending']
        assert result['report']['cleanup_error'] == 'vector index unavailable'
        assert 'cleanup incomplete:' in status['state']['last_error']
        assert any(c['collection'] == old and c['status'] == 'retired' for c in status['collections'])
        code, _ = __import__('phase_b_checks').request(r.qurl, '/collections/' + old)
        assert code == 200
        r.counter += 1
        r.save('recovery-retention-' + str(r.counter), {'old': old, 'operation': result, 'status': status, 'inventory': r.inventory()})
        return old, result

    old, retained = create_retired()

    def persistent():
        before = publication()
        failed = measured('sync')
        after = publication()
        status = r.cli('status')
        assert before == after
        assert failed['report']['verified_unchanged'] and not failed['report']['published']
        assert failed['report']['cleanup_pending'] == [old]
        assert failed['report']['cleanup_error'] == 'vector index unavailable'
        assert status['verified_healthy'] and old in [c['collection'] for c in status['collections']]
        assert 'cleanup incomplete: 1 leftover collection(s) remain' in status['state']['last_error']
        before_counts = provider.snapshot()
        text = r.command([r.work/'semantic-index', '-batch', '2', 'sync'], routed)
        status_text = r.command([r.work/'semantic-index', 'status'])
        assert provider.wait_idle()
        assert_embedding_delta(before_counts, provider.snapshot())
        assert 'nothing written' in text['stdout']
        assert 'cleanup incomplete:' not in text['stdout']
        assert old not in text['stdout']
        assert 'cleanup incomplete:' in status_text['stdout'] and old in status_text['stdout']
        return {'retention': retained, 'sync': failed, 'status': status,
                'publication_before': before, 'publication_after': after,
                'cli_sync_text': text, 'cli_status_text': status_text,
                'visibility_limit': 'default sync text hides pending cleanup; -json and status expose it'}
    r.case('recovery-persistent-cleanup-failure', 'retained actual collection/record, JSON pending/error and status last_error; zero embeddings; record default CLI limitation', persistent)

    def only_healthy():
        from phase_b_checks import request
        before = publication()
        proxy.delete_failures.clear()
        cleaned = measured('sync')
        after = publication()
        status = r.cli('status')
        code, missing = request(r.qurl, '/collections/' + old)
        assert before == after
        assert code == 404, missing
        assert cleaned['report']['verified_unchanged'] and not cleaned['report']['published']
        assert cleaned['report']['cleaned_collections'] == 1 and cleaned['report']['cleanup_pending'] == []
        assert not cleaned['report'].get('cleanup_error') and status['state']['last_error'] == ''
        assert all(c['collection'] != old for c in status['collections'])
        with sqlite3.connect(r.env['DB_PATH']) as db:
            assert db.execute('SELECT count(*) FROM semantic_index_manifest WHERE collection=?', (old,)).fetchone()[0] == 0
        return {'sync': cleaned, 'collection_get_status': code, 'status': status,
                'publication_before': before, 'publication_after': after, 'inventory': r.verify()}
    r.case('recovery-f2-only-healthy-sync', 'after fault removal ONLY healthy sync deletes actual old collection/record/manifest; exact publication/cache/points unchanged; zero embeddings', only_healthy)

    # Recreate two actually present retired leftovers, retaining failures across runs.
    first, _ = create_retired()
    second, _ = create_retired()
    proxy.delete_failures.clear()
    def lease_loss():
        before = provider.snapshot()
        result = r.probe('recovery-cleanup-lease-loss', r.env['DB_PATH'])
        assert provider.wait_idle()
        assert_embedding_delta(before, provider.snapshot())
        assert set(result['eligible']) == {first, second}
        assert result['pass'] and len(result['deletions']) == 1
        result['provider_before'], result['provider_after'] = before, provider.snapshot()
        return result
    r.case('recovery-cleanup-lease-loss', 'one already-gated terminal deletion may finish; no subsequent delete or fenced bookkeeping; full newer publication equal', lease_loss)
    def heal():
        prior = publication()
        sync = measured('sync', r.env)
        assert sync['report']['verified_unchanged'] and sync['report']['cleanup_pending'] == []
        assert sync['report']['cleaned_collections'] == 2
        assert prior == publication()
        return {'sync': sync, 'inventory': r.verify()}
    r.case('recovery-cleanup-after-lease-loss', 'next healthy sync reconciles retained records including already missing collection without embedding', heal)

    writing_names = []
    def writing():
        before = provider.snapshot()
        result = r.probe('recovery-cleanup-writing', r.env['DB_PATH'])
        assert provider.wait_idle()
        assert_embedding_delta(before, provider.snapshot())
        name = result['writing_collection']
        writing_names.append(name)
        status = r.cli('status')
        text = r.command([r.work/'semantic-index', 'status'])
        assert status['verified_healthy'] and 'cleanup incomplete:' in status['state']['last_error']
        assert name in text['stdout'] and 'removed by the next run' in text['stdout']
        # A second healthy sync still cannot remove another run's writing record.
        again = measured('sync', r.env)
        assert again['report']['cleanup_pending'] == [name] and again['report']['cleaned_collections'] == 0
        from phase_b_checks import request
        assert request(r.qurl, '/collections/' + name)[0] == 200
        result.update(second_sync=again, status=status, cli_status_text=text,
                      visibility_limit='status promises next-run removal for writing, although healthy sync deliberately retains it')
        return result
    r.case('recovery-other-writing-collection', 'healthy sync keeps other writing points/manifest/record and reports pending; distinguish text visibility mismatch', writing)
    def publishing_cleanup():
        from phase_b_checks import request
        assert len(writing_names) == 1
        name = writing_names[0]
        rebuilt = measured('rebuild', r.env)
        assert rebuilt['report']['published'] and rebuilt['report']['cleanup_pending'] == []
        assert request(r.qurl, '/collections/' + name)[0] == 404
        with sqlite3.connect(r.env['DB_PATH']) as db:
            assert db.execute('SELECT count(*) FROM semantic_index_physical_collections WHERE collection=?', (name,)).fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM semantic_index_manifest WHERE collection=?', (name,)).fetchone()[0] == 0
        return {'rebuild': rebuilt, 'removed_writing_collection': name, 'inventory': r.verify()}
    r.case('recovery-writing-publishing-cleanup', 'a later publishing rebuild removes the superseded writing collection from actual Qdrant and bookkeeping using cache', publishing_cleanup)
    r.save('recovery-provider-complete-ledger', provider.snapshot())
    r.save('recovery-proxy-complete-ledger', proxy.events)
