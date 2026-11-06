import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import cv2
import numpy as np

from src.task.NightmareNestTask import NightmareNestTask
from tests.TestNightmareNestTask import FakeBox


LAYOUT = json.loads((Path(__file__).parent / 'fixtures/nightmare_nest_scan.json').read_text())


class NightmareNestScanTest(unittest.TestCase):
    def task(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.tr = str
        task._executor = SimpleNamespace(frame=np.zeros((1080, 1920, 3), dtype=np.uint8))
        for name in ('openF2Book', 'open_boss_book', 'sleep', 'next_frame', 'click', 'log_info'):
            setattr(task, name, Mock())
        return task

    def image(self, thumb, size=(1920, 1080)):
        width, height = size
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.rectangle(frame, (int(width * .9728), int(height * thumb[0])),
                      (int(width * .9737), int(height * thumb[1])), (220, 220, 220), -1)
        return frame

    def test_empty_top_scan_retries_without_advancing_queue(self):
        task = self.task()
        top = Mock(__name__='go_nest')
        bottom = Mock(__name__='go_nest_scroll')
        task.queues = [top, bottom]
        target = object()
        task.find_nest = Mock(side_effect=[None, target])
        task._save_empty_nest_scan = Mock()
        self.assertIs(task.get_nest_to_go(), target)
        bottom.assert_not_called()
        self.assertEqual(task.queues, [top, bottom])
        task._save_empty_nest_scan.assert_called_once()
        task.next_frame.assert_called_once()

    def test_empty_bottom_is_followed_by_top_recheck_before_nightmare(self):
        task = self.task()
        task.config = {'Which to Farm': ['Tacet Discord Nest', 'Nightmare Purification']}
        task._init_queue()
        names = [action.__name__ for action in task.queues]
        actions = [Mock(__name__=name) for name in names]
        task.queues = actions.copy()
        target = object()
        task.find_nest = Mock(side_effect=[None] * 6 + [target])
        task._save_empty_nest_scan = Mock()
        self.assertIs(task.get_nest_to_go(), target)
        self.assertEqual(task._nest_tab_of_current_nest, 'go_nest')
        for action in actions[:3]:
            action.assert_called_once()
        for action in actions[3:]:
            action.assert_not_called()

    def test_empty_pages_have_bounded_retries(self):
        task = self.task()
        task.queues = [Mock(__name__='go_nest'), Mock(__name__='go_nest_scroll')]
        task.find_nest = Mock(return_value=None)
        task._save_empty_nest_scan = Mock()
        self.assertIsNone(task.get_nest_to_go())
        self.assertEqual(task.find_nest.call_count, 6)
        self.assertEqual(task.queues, [])

    def test_five_nests_remain_reachable_after_first_empty_scan(self):
        task = self.task()
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task._unreachable_nests = set()
        task.height_of_screen = lambda value: 1080 * value
        task.width_of_screen = lambda value: 1920 * value
        remaining = set(range(5))
        task.empty_first = True

        def go_nest():
            task.page = 'top'

        def go_nest_scroll():
            task.page = 'bottom'

        task.go_nest, task.go_nest_scroll = go_nest, go_nest_scroll
        task.config = {'Which to Farm': ['Tacet Discord Nest']}
        task._init_queue()
        task._save_empty_nest_scan = Mock()

        def ocr(x, y, to_x, to_y, **kwargs):
            if task.empty_first:
                task.empty_first = False
                return []
            layout = list(enumerate(LAYOUT['topCounts'])) if task.page == 'top' else [
                (0, LAYOUT['bottomHalfRow']), (1, ['0/41', .36]),
                (2, ['0/48', .565]), (3, ['0/48', .707]), (4, ['0/24', .849])]
            boxes = []
            for item, (text, position) in layout:
                if item in remaining and y < position < to_y:
                    box = FakeBox(text, y=round(position * 1080))
                    box.item = item
                    boxes.append(box)
            return boxes

        task.ocr = ocr
        selected = []
        while target := task.get_nest_to_go():
            selected.append(target.box.item)
            remaining.remove(target.box.item)  # Simulate completing that nest.
        self.assertEqual(selected, [0, 1, 2, 3, 4])
        self.assertEqual(remaining, set())

    def test_failed_diagnostic_write_can_retry(self):
        task = self.task()
        task.queues = [Mock(__name__='go_nest')]
        task._last_nest_frame = np.zeros((1080, 1920, 3), np.uint8)
        task._last_nest_ocr = []
        with patch('src.task.NightmareNestTask.cv2.imencode', return_value=(False, None)):
            task._save_empty_nest_scan()
        self.assertFalse(getattr(task, '_empty_nest_scan_saved', False))

    def test_scrollbar_layout_at_supported_resolutions(self):
        for size in ((1280, 720), (1920, 1080), (3840, 2160)):
            with self.subTest(size=size):
                self.assertTrue(NightmareNestTask._nest_scrollbar_at_top(self.image(LAYOUT['topThumb'], size)))
                self.assertFalse(NightmareNestTask._nest_scrollbar_at_top(self.image(LAYOUT['bottomThumb'], size)))
                self.assertFalse(NightmareNestTask._nest_scrollbar_at_top(np.zeros((size[1], size[0], 3), np.uint8)))

    def test_top_click_retries_and_requires_two_confirmations(self):
        task = self.task()
        task._save_empty_nest_scan = Mock()
        with patch.object(NightmareNestTask, 'frame', self.image(LAYOUT['topThumb'])), patch.object(
                task, '_nest_scrollbar_at_top', side_effect=[False, True, True]):
            task.go_nest()
        self.assertEqual(task.click.call_count, 2)
        self.assertEqual(task.next_frame.call_count, 3)
        task.click.assert_called_with(.9730, .197, after_sleep=.6)

    def test_unconfirmed_top_stops_instead_of_silently_skipping(self):
        task = self.task()
        task._save_empty_nest_scan = Mock()
        with patch.object(NightmareNestTask, 'frame', self.image(LAYOUT['bottomThumb'])):
            with self.assertRaisesRegex(RuntimeError, 'top could not be confirmed'):
                task.go_nest()
        self.assertEqual(task.click.call_count, 3)
        task._save_empty_nest_scan.assert_called_once_with(reason='top-not-confirmed')

    def test_progress_filter_and_half_row_boundary_are_unchanged(self):
        task = self.task()
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task.queues = [Mock(__name__='go_nest')]
        task._unreachable_nests = set()
        task.height_of_screen = lambda value: 1080 * value
        task.width_of_screen = lambda value: 1920 * value
        boxes = [FakeBox('1/48', y=390), FakeBox('48/48', y=390), FakeBox('0/99', y=390)]
        task.ocr = Mock(return_value=boxes)
        self.assertIsNone(task.find_nest())
        self.assertEqual(task.ocr.call_args.args, (.35, .25, 1, .96))
        boxes.append(FakeBox('0/48', y=int(LAYOUT['topCounts'][0][1] * 1080)))
        self.assertIsNotNone(task.find_nest())
        self.assertLess(LAYOUT['bottomHalfRow'][1], task.ocr.call_args.args[1])

    def test_unmatched_ocr_text_is_kept_for_empty_scan_diagnosis(self):
        task = self.task()
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task.queues = [Mock(__name__='go_nest')]
        raw = FakeBox('O/48', y=390)
        # Model the OCR API's optional filtering: a misread must survive in
        # diagnostics even though it is not eligible to be selected.
        task.ocr = Mock(side_effect=lambda *args, **kwargs:
                        [raw] if not kwargs.get('match') or kwargs['match'].search(raw.name) else [])
        self.assertIsNone(task.find_nest())
        self.assertEqual(task._last_nest_ocr[0]['name'], 'O/48')

    def test_diagnostics_keep_exact_ocr_and_exclude_account_strip(self):
        task = self.task()
        task.queues = [Mock(__name__='go_nest')]
        task._last_nest_ocr = [{'name': '48/48', 'x': 800, 'y': 390, 'width': 100, 'height': 20}]
        task._last_nest_frame = np.zeros((1080, 1920, 3), np.uint8)
        with tempfile.TemporaryDirectory() as folder, patch('src.task.NightmareNestTask.Path',
                side_effect=lambda value: Path(folder) / value), patch.object(
                NightmareNestTask, 'frame', np.zeros((1080, 1920, 3), np.uint8)):
            task._save_empty_nest_scan()
            task._save_empty_nest_scan()
            saved = list(Path(folder).rglob('*.json'))
            self.assertEqual(len(saved), 1)
            self.assertEqual(json.loads(saved[0].read_text())['counts'], task._last_nest_ocr)
            image = cv2.imread(str(saved[0].with_suffix('.png')))
            self.assertEqual(image.shape[:2], (int(1080 * .96) - int(1080 * .13), 1920 - int(1920 * .35)))

    def test_top_failure_diagnostic_does_not_reuse_previous_ocr(self):
        task = self.task()
        task.queues = [Mock(__name__='go_nest')]
        task._last_nest_ocr = [{'name': 'old-page'}]
        with tempfile.TemporaryDirectory() as folder, patch('src.task.NightmareNestTask.Path',
                side_effect=lambda value: Path(folder) / value):
            task._save_empty_nest_scan(reason='top-not-confirmed')
            saved = next(Path(folder).rglob('*.json'))
            payload = json.loads(saved.read_text())
            self.assertIsNone(payload['counts'])
            self.assertEqual(payload['ocrStatus'], 'not-run')
            self.assertFalse(getattr(task, '_empty_nest_scan_saved', False))


if __name__ == '__main__':
    unittest.main()
