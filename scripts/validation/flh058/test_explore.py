"""Offline tests only: fake HTTP objects, no endpoint/model/socket calls."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('explore', Path(__file__).with_name('explore.py'))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class Reply:
    code = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return b'{"data":[]}'


class Handler:
    def __init__(self, body):
        self.path = '/v1/embeddings'
        self.headers = {'Content-Length':str(len(body))}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
    def send_response(self, status): self.status = status
    def send_header(self, *args): pass
    def end_headers(self): pass


def batch():
    return [json.dumps({'representation':'concept_embedding_text_v1', 'type':'query' if i==0 else 'concept'}) for i in range(25)]


class OfflineTests(unittest.TestCase):
    def test_metric_truncation_null_and_zero(self):
        self.assertIsNone(e.metric([])['mrr_at_5'])
        self.assertEqual(e.metric([{'rank':None}])['mrr_at_5'],0)
        m=e.metric([{'rank':1},{'rank':3},{'rank':5},{'rank':6},{'rank':None}])
        self.assertEqual((m['hits_at_1'],m['hits_at_3'],m['hits_at_5']),(1,2,3))
        self.assertAlmostEqual(m['mrr_at_5'],(1+1/3+1/5)/5)

    def test_forwarder_preserves_bytes_single_attempt(self):
        with tempfile.TemporaryDirectory(prefix='flh058-unit-') as directory:
            b=batch();r=e.Recorder(Path(directory),[b])
            body=json.dumps({'model':e.MODEL,'input':b},indent=2).encode()
            h=Handler(body)
            with patch.object(e,'opener') as op:
                op.return_value.open.return_value=Reply()
                r.handle(h)
                op.return_value.open.assert_called_once()
                request=op.return_value.open.call_args.args[0]
                self.assertEqual(request.data,body)
                self.assertEqual(request.full_url,e.BASE+'/embeddings')
            self.assertEqual(h.status,200)
            self.assertEqual(r.positions,25)
            self.assertEqual(r.calls[0]['upstream_attempts'],1)

    def test_caps_and_input_drift_refuse_before_upstream(self):
        for mode in ('request_cap','position_cap','text_drift'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='flh058-unit-') as directory:
                b=batch();r=e.Recorder(Path(directory),[b]*56)
                if mode=='request_cap': r.calls=[{}]*56
                if mode=='position_cap': r.positions=1400
                submitted=b.copy()
                if mode=='text_drift': submitted[0]+=' '
                h=Handler(json.dumps({'model':e.MODEL,'input':submitted}).encode())
                with patch.object(e,'opener') as op:
                    r.handle(h)
                    op.assert_not_called()
                self.assertEqual(h.status,502)
                self.assertTrue(r.abort)

    def test_upstream_timeout_has_no_retry(self):
        with tempfile.TemporaryDirectory(prefix='flh058-unit-') as directory:
            b=batch();r=e.Recorder(Path(directory),[b]);h=Handler(json.dumps({'model':e.MODEL,'input':b}).encode())
            with patch.object(e,'opener') as op:
                op.return_value.open.side_effect=TimeoutError()
                r.handle(h)
                op.return_value.open.assert_called_once()
            self.assertTrue(r.abort)
            self.assertEqual(r.positions,25)
            self.assertEqual(h.status,502)
            self.assertTrue((Path(directory)/'forwarder-failure.json').exists())

    def test_reservation_blocks_before_readiness(self):
        with tempfile.TemporaryDirectory(prefix='flh058-unit-') as directory:
            ledger=Path(directory)/'reservation.json';ledger.write_text('{}')
            with patch.object(e,'LEDGER',ledger),patch.object(e,'read_endpoint') as read:
                with self.assertRaises(AssertionError): e.run_once(Path(directory))
                read.assert_not_called()


if __name__=='__main__': unittest.main()
