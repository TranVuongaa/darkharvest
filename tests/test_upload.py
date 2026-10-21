import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from upload_knowledge import CHUNKING_STRATEGY, MANAGER, estimate_chunks, resolve_store, synchronize


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'inbound-123.md'
        self.content = ('---\ntitle: "Before --- After"\n'
                        'source: "https://example.com/article"\n---\n'
                        '# Before --- After\n\n[Relative](/hc/article)\n\n'
                        '```python\nif True:\n\n    second()\n```\n').encode()
        self.path.write_bytes(self.content)
        self.client = MagicMock()
        self.remote = []
        self.client.vector_stores.files.list.side_effect = lambda **kw: list(self.remote)
        self.client.files.create.side_effect = lambda **kw: SimpleNamespace(id=f'file-{len(self.remote)}')

        def attach(**kw):
            file = SimpleNamespace(id=kw['file_id'], attributes=kw['attributes'],
                                   status='completed', last_error=None)
            self.remote.append(file)
            return file

        def detach(file_id, **kw):
            self.remote[:] = [f for f in self.remote if f.id != file_id]

        self.client.vector_stores.files.create_and_poll.side_effect = attach
        self.client.vector_stores.files.delete.side_effect = detach

    def sync(self, paths=None):
        return synchronize(self.client, 'vs-test', paths or [self.path])

    def test_one_file_exact_bytes_and_rerun_skips(self):
        self.assertEqual(self.sync(), dict(added=1, updated=0, uploaded=1, skipped=0, failed=0,
                                           embedded_files=1, embedded_chunks_estimated=1))
        self.assertEqual(self.client.files.create.call_args.kwargs['file'][1], self.content)
        self.assertEqual(self.sync(), dict(added=0, updated=0, uploaded=0, skipped=1, failed=0,
                                           embedded_files=0, embedded_chunks_estimated=0))
        self.client.files.create.assert_called_once()

    def test_fresh_directory_reuses_remote_metadata(self):
        self.sync()
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory) / self.path.name
            fresh.write_bytes(self.content)
            self.assertEqual(self.sync([fresh])['skipped'], 1)
        self.client.files.create.assert_called_once()

    def test_chunk_estimate_boundaries(self):
        with patch('upload_knowledge.tiktoken.get_encoding') as encoding:
            for tokens, expected in [(0, 0), (1, 1), (800, 1), (801, 2),
                                     (1200, 2), (1201, 3), (2000, 4)]:
                with self.subTest(tokens=tokens):
                    encoding.return_value.encode_ordinary.return_value = [0] * tokens
                    self.assertEqual(estimate_chunks('text'), expected)

    def test_explicit_chunking_and_embedding_log(self):
        with patch('upload_knowledge.estimate_chunks', return_value=3):
            with self.assertLogs('optibot.ingestion', level='INFO') as logs:
                counts = self.sync()
        self.assertEqual(counts['embedded_files'], 1)
        self.assertEqual(counts['embedded_chunks_estimated'], 3)
        self.assertIn('embedded_files=1 embedded_chunks_estimated=3', '\n'.join(logs.output))
        self.assertEqual(
            self.client.vector_stores.files.create_and_poll.call_args.kwargs['chunking_strategy'],
            CHUNKING_STRATEGY,
        )

    def test_rename_keeps_stable_id(self):
        self.sync()
        renamed = self.path.with_name('new-title-123.md')
        self.path.rename(renamed)
        self.assertEqual(self.sync([renamed])['skipped'], 1)
        self.client.files.create.assert_called_once()

    def test_change_replaces_after_indexing(self):
        self.sync()
        old = self.remote[0]
        self.path.write_bytes(self.content + b'New text\n')
        counts = self.sync()
        self.assertEqual(counts['uploaded'], 1)
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(counts['added'], 0)
        self.assertEqual(len(self.remote), 1)
        self.assertNotEqual(self.remote[0].id, old.id)
        self.client.files.delete.assert_not_called()

    def test_indexing_failure_retains_old_and_continues(self):
        self.sync()
        old = self.remote[0]
        self.path.write_bytes(self.content + b'Changed\n')
        other = self.root / 'other-456.md'
        other.write_bytes(self.content)
        attach = self.client.vector_stores.files.create_and_poll.side_effect
        self.client.vector_stores.files.create_and_poll.side_effect = [
            SimpleNamespace(status='failed', last_error='bad input'),
            attach(file_id='other', attributes={'manager': MANAGER, 'article_key': '456'}),
        ]
        with self.assertLogs('optibot.ingestion', level='ERROR'):
            result = self.sync([self.path, other])
        self.assertEqual(result, dict(added=0, updated=1, uploaded=1, skipped=0, failed=1,
                                      embedded_files=1, embedded_chunks_estimated=1))
        self.assertIn(old, self.remote)
        self.client.files.delete.assert_called_once()
        self.client.vector_stores.files.delete.assert_not_called()

    def test_interrupted_replacement_cleanup_on_rerun(self):
        self.sync()
        self.path.write_bytes(self.content + b'Changed\n')
        detach = self.client.vector_stores.files.delete.side_effect
        self.client.vector_stores.files.delete.side_effect = RuntimeError('network')
        with self.assertLogs('optibot.ingestion', level='ERROR'):
            result = self.sync()
            self.assertEqual(result['failed'], 1)
            self.assertEqual(result['embedded_files'], 1)
            self.assertEqual(result['embedded_chunks_estimated'], 1)
        self.assertEqual(len(self.remote), 2)
        self.client.vector_stores.files.delete.side_effect = detach
        self.assertEqual(self.sync()['skipped'], 1)
        self.assertEqual(len(self.remote), 1)
        self.assertEqual(self.client.files.create.call_count, 2)

    def test_unmanaged_files_are_untouched(self):
        old = SimpleNamespace(id='legacy', attributes={}, status='completed')
        self.remote.append(old)
        self.sync()
        self.assertIn(old, self.remote)
        self.client.vector_stores.files.delete.assert_not_called()

    def test_duplicate_input_ids_rejected_before_upload(self):
        other = self.root / 'stale-title-123.md'
        other.write_bytes(self.content)
        with self.assertRaisesRegex(ValueError, 'Duplicate article IDs'):
            self.sync([self.path, other])
        self.client.files.create.assert_not_called()

    def test_store_comes_only_from_configuration(self):
        self.assertEqual(resolve_store(self.client, ' vs-configured '), 'vs-configured')
        self.client.vector_stores.retrieve.assert_called_once_with('vs-configured')
        self.client.vector_stores.create.assert_not_called()

    def test_missing_store_does_not_create_or_reuse_one(self):
        for value in (None, '', '   '):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'OPENAI_VECTOR_STORE_ID'):
                resolve_store(self.client, value)
        self.client.vector_stores.retrieve.assert_not_called()
        self.client.vector_stores.create.assert_not_called()

    def test_invalid_store_does_not_create_replacement(self):
        self.client.vector_stores.retrieve.side_effect = RuntimeError('store not found')
        with self.assertRaisesRegex(RuntimeError, 'store not found'):
            resolve_store(self.client, 'vs-invalid')
        self.client.vector_stores.create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
