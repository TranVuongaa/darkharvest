import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from upload_knowledge import MANAGER, resolve_store, synchronize


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
        self.assertEqual(self.sync(), dict(uploaded=1, skipped=0, failed=0))
        self.assertEqual(self.client.files.create.call_args.kwargs['file'][1], self.content)
        self.assertEqual(self.sync(), dict(uploaded=0, skipped=1, failed=0))
        self.client.files.create.assert_called_once()

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
        self.assertEqual(self.sync()['uploaded'], 1)
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
        self.assertEqual(result, dict(uploaded=1, skipped=0, failed=1))
        self.assertIn(old, self.remote)
        self.client.files.delete.assert_called_once()
        self.client.vector_stores.files.delete.assert_not_called()

    def test_interrupted_replacement_cleanup_on_rerun(self):
        self.sync()
        self.path.write_bytes(self.content + b'Changed\n')
        detach = self.client.vector_stores.files.delete.side_effect
        self.client.vector_stores.files.delete.side_effect = RuntimeError('network')
        with self.assertLogs('optibot.ingestion', level='ERROR'):
            self.assertEqual(self.sync()['failed'], 1)
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

    def test_store_persisted_and_reused(self):
        state = self.root / 'state.json'
        self.client.vector_stores.create.return_value.id = 'vs-test'
        self.assertEqual(resolve_store(self.client, state, None), 'vs-test')
        self.assertEqual(resolve_store(self.client, state, None), 'vs-test')
        self.client.vector_stores.create.assert_called_once()
        with self.assertRaises(ValueError):
            resolve_store(self.client, state, 'vs-other')


if __name__ == '__main__':
    unittest.main()
