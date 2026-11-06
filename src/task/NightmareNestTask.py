import re
import cv2
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from dataclasses import dataclass

from ok import Logger
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedException
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.task_icons import task_icon

logger = Logger.get_logger(__name__)
TRAVEL_FEATURES = ['fast_travel_custom', 'gray_teleport', 'remove_custom']
CONFIRM_FEATURES = ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter']


@dataclass
class NestTarget:
    box: object
    cache_key: str


class NightmareNestTask(WWOneTimeTask, BaseCombatTask):
    max_nest_deaths = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.target_enemy_time_out = 10
        self.name = "🌙 Nightmare Nest Task"
        self.icon = task_icon('nightmare')
        self.group_name = 'Daily Activities'
        self.group_icon = task_icon('category-daily')
        self.description = "Auto Farm all Nightmare Nest"
        self.support_schedule_task = True
        self.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        self.queues = []
        self._capture_success = False
        self._capture_mode = False
        self._unreachable_nests = set()
        self._nest_deaths = {}
        self._nest_tab_of_current_nest = 'go_nest'
        self.default_config.update({'Which to Farm': ['Nightmare Purification', 'Tacet Discord Nest']})
        self.config_type['Which to Farm'] = {'type': "multi_selection",
                                             'options': ['Nightmare Purification', 'Tacet Discord Nest']}

    def run(self):
        self._capture_mode = False
        self._capture_success = False
        self._unreachable_nests.clear()
        self._nest_deaths.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info(self.tr('opened gray_book_boss'))
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
        self.ensure_main(time_out=30)

    def run_capture_mode(self):
        self._capture_mode = True
        self._capture_success = False
        self._unreachable_nests.clear()
        self._nest_deaths.clear()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info(self.tr('opened gray_book_boss'))
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
            if self._capture_success:
                break
        self.ensure_main(time_out=30)

    def on_combat_check(self):
        if self._capture_mode:
            self.pick_f(handle_claim=False)
            if self.has_echo_notification():
                return self.reset_to_false(reason='echo captured')
        return True

    def has_echo_notification(self):
        if self.find_best_match_in_box(self.box_of_screen(0.078, 0.488, 0.094, 0.514),
                                       ['char_1_text', 'char_3_text'], 0.6,
                                       frame_processor=convert_image_to_negative):
            self._capture_success = True
        return self._capture_success

    def combat_nest(self, nest):
        target_box = nest.box if isinstance(nest, NestTarget) else nest
        self.click(target_box, after_sleep=2)
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)
        is_team = feature.name == 'team_close'
        if is_team:
            self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
        else:
            if not self._travel_to_nest_or_skip(nest):
                return
            self.sleep(1)
            while self.find_f_with_text():
                self.send_key('f', after_sleep=1)
                self.wait_in_team_and_world(time_out=40, raise_if_not_found=False)
            self.sleep(2)
            self.run_until(self.in_combat, 'w', time_out=10, running=False, target=True)
        wait_combat_time = 10
        while True:
            try:
                need_find = self.combat_once(wait_combat_time=wait_combat_time, target=True,
                                             raise_if_not_found=False)
            except CharRevivedException:
                if isinstance(nest, NestTarget):
                    deaths = self._nest_deaths.get(nest.cache_key, 0) + 1
                    self._nest_deaths[nest.cache_key] = deaths
                    if deaths >= self.max_nest_deaths:
                        self._unreachable_nests.add(nest.cache_key)
                        self.log_info(self.tr('nightmare nest: died {deaths} times, skip this run: {cache_key}').format(deaths=deaths, cache_key=nest.cache_key),
                                      notify=True)
                        return
                self.log_info(self.tr('nightmare nest: death recovered, re-enter from F2 book'))
                return
            captured_early = False
            if self._capture_mode:
                if self._capture_success or self.wait_until(self.has_echo_notification, time_out=3):
                    self.log_info(self.tr('Captured echo during combat, skipping search.'))
                    captured_early = True
            if not captured_early:
                self.sleep(3)
                if need_find and not self.walk_find_echo(time_out=5, backward_time=2.5):
                    dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                    logger.info(f'farm echo yolo find {dropped}')
                    if not dropped and not is_team:
                        # 保底：没有收取到声骸时，重新打开图鉴传送回当前聚落（传送点面朝金色声骸群），再搜索一次
                        self.log_info(self.tr('no echo collected, re-teleport to current nest as fallback'))
                        self.ensure_main(time_out=30)
                        self.openF2Book("gray_book_boss")
                        getattr(self, self._nest_tab_of_current_nest)()
                        self.sleep(1)
                        self.click(target_box, after_sleep=2)
                        if self.wait_feature(TRAVEL_FEATURES, time_out=5, settle_time=0.5,
                                            raise_if_not_found=False) and self._travel_to_nest_or_skip(nest):
                            self.sleep(2)
                            self.run_until(lambda: False, 'w', time_out=2, running=True)
                            if not self.walk_find_echo(time_out=5, backward_time=2.5):
                                dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                                logger.info(f'farm echo yolo find after re-teleport {dropped}')
                            else:
                                dropped = True
                                self.log_info(self.tr('farm echo walk find true after re-teleport'))
                else:
                    dropped = True
                    self.log_info(self.tr('farm echo walk find true'))
                self._capture_success = dropped
            if not self._should_continue_combat_after_pickup():
                break
            self.log_info(self.tr('nightmare nest: combat detected after pickup'))
            wait_combat_time = 1
        # 与刷全部一致：退本后再结束 combat_nest，避免还在巢穴内回 Daily/开书
        if is_team:
            self.esc_world_confirm()
        self.sleep(1)

    def _should_continue_combat_after_pickup(self):
        return not self._capture_mode and self.wait_combat(
            target=True, time_out=3, raise_if_not_found=False)

    def _travel_to_nest_or_skip(self, nest):
        travel = self.wait_until(self._find_travel_button, raise_if_not_found=False, time_out=1)
        if travel:
            self.click(travel, after_sleep=1)
            if confirm := self._find_first_feature(CONFIRM_FEATURES, threshold=0.6):
                self.click(confirm, after_sleep=1)

        button_still_visible = travel and self.find_one(travel.name, threshold=0.7)
        if travel and not button_still_visible and self.wait_in_team_and_world(
                time_out=120, raise_if_not_found=False):
            return True

        if isinstance(nest, NestTarget):
            self._unreachable_nests.add(nest.cache_key)
            self.log_info(self.tr('nightmare nest unreachable, skip this run: {cache_key}').format(cache_key=nest.cache_key))
        else:
            self.log_info(self.tr('nightmare nest unreachable, skip this run'))
        self.back(after_sleep=1)
        return False

    def _find_travel_button(self):
        return self._find_first_feature(TRAVEL_FEATURES, threshold=0.7)

    def _find_first_feature(self, feature_names, threshold):
        for feature_name in feature_names:
            if feature := self.find_one(feature_name, threshold=threshold):
                return feature

    def get_nest_to_go(self):
        self.openF2Book("gray_book_boss")

        while self.queues:
            action = self.queues[0]
            action()
            # A single empty OCR result is not evidence that this page is done.
            for attempt in range(3):
                if nest := self.find_nest():
                    self._nest_tab_of_current_nest = action.__name__
                    return nest
                if action.__name__ == 'go_nest' and attempt == 0:
                    self._save_empty_nest_scan()
                if attempt < 2:
                    self.sleep(0.5)
                    self.next_frame()
            self.queues.pop(0)

    def _init_queue(self):
        quests = self.config.get('Which to Farm') or ['Nightmare Purification', 'Tacet Discord Nest']
        actions = []
        if 'Tacet Discord Nest' in quests:
            actions.append(self.go_nest)
            actions.append(self.go_nest_scroll)
            # Revisit the first page before the nightmare tab changes the scroll.
            # Reuse go_nest so unreachable/death cache keys remain identical.
            actions.append(self.go_nest)
        if 'Nightmare Purification' in quests:
            actions.append(self.go_nightmare)
            actions.append(self.go_nightmare_scroll)
        self.queues = actions
        self._empty_nest_scan_saved = False
        self._last_nest_ocr = []
        self._last_nest_frame = None

    def go_nightmare(self):
        self.open_boss_book('mengyan')
        self.log_info(self.tr('go nightmare'))

    def go_nightmare_scroll(self):
        self.open_boss_book('mengyan')
        self.click(3737 / 3840, 0.54, after_sleep=1)
        self.log_info(self.tr('go nightmare scroll'))

    def go_nest(self):
        self.open_boss_book('canxiang')
        # PR #1719 measured the thumb at .197-.761 (top) and .319-.882
        # (bottom). Click the track above the latter; never use wheel/drag.
        for _ in range(3):
            self.click(0.9730, 0.197, after_sleep=0.6)
            self.next_frame()
            if self._nest_scrollbar_at_top(self.frame):
                self.sleep(0.4)
                self.next_frame()
                if self._nest_scrollbar_at_top(self.frame):
                    return
        self._save_empty_nest_scan(reason='top-not-confirmed')
        raise RuntimeError('Nightmare nest list top could not be confirmed')

    @staticmethod
    def _nest_scrollbar_at_top(frame):
        if frame is None or not frame.size:
            return False
        height, width = frame.shape[:2]
        # Only inspect the thin scrollbar, not the bright cards behind it.
        strip = frame[int(height * .19):int(height * .89),
                      int(width * .972):int(width * .9745)]
        if not strip.size:
            return False
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        rows = (gray > 160).any(axis=1).nonzero()[0]
        start = previous = None
        for row in rows:
            if previous is None or row - previous > 2:
                start = row
            if row - start >= height * .3 and start + int(height * .19) <= height * .215:
                return True
            previous = row
        return False

    def _save_empty_nest_scan(self, reason='empty'):
        if reason == 'empty' and getattr(self, '_empty_nest_scan_saved', False):
            return
        # Keep diagnostics local, outside tracked sources. Crop out the bottom
        # account identifier; preserve exactly the frame used by the last OCR.
        try:
            frame = self._last_nest_frame if reason == 'empty' else self.frame
            height, width = frame.shape[:2]
            folder = Path('logs') / 'nightmare-nest'
            folder.mkdir(parents=True, exist_ok=True)
            stem = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8]
            crop = frame[int(height * .13):int(height * .96), int(width * .35):]
            success, encoded = cv2.imencode('.png', crop)
            if not success:
                raise RuntimeError('Could not encode nightmare nest diagnostic')
            (folder / (stem + '.png')).write_bytes(encoded.tobytes())
            payload = {'reason': reason, 'action': self.queues[0].__name__,
                       'frameSize': [width, height], 'ocrRegion': [.35, .25, 1, .96],
                       'ocrStatus': 'completed' if reason == 'empty' else 'not-run',
                       'counts': self._last_nest_ocr if reason == 'empty' else None}
            (folder / (stem + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            if reason == 'empty':
                self._empty_nest_scan_saved = True
            self.log_info(f'Nightmare nest diagnostic saved: {folder / stem}')
        except Exception as error:
            self.log_info(f'Could not save nightmare nest diagnostic: {error}')

    def go_nest_scroll(self):
        self.open_boss_book('canxiang')
        self.click(0.9730, 0.8806, after_sleep=1)

    def find_nest(self):
        self._last_nest_frame = self.frame.copy()
        counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re, frame=self._last_nest_frame)
        self._last_nest_ocr = [dict(name=box.name, x=box.x, y=box.y,
                                    width=box.width, height=box.height) for box in counts]
        for count_box in counts:
            for match in re.finditer(self.count_re, count_box.name):
                numerator = match.group(1)
                denominator = match.group(2)
                if numerator != denominator and denominator in ['24', '36', '48', '41'] and numerator == '0':
                    cache_key = self._make_nest_cache_key(count_box, denominator)
                    if cache_key in self._unreachable_nests:
                        self.log_info(self.tr('skip cached unreachable nightmare nest: {cache_key}').format(cache_key=cache_key))
                        continue
                    self.log_info(self.tr('{count_box} is not complete').format(count_box=count_box))
                    count_box.x = self.width_of_screen(0.9)
                    count_box.y -= count_box.height * 0.9
                    count_box.height = 1
                    count_box.width = 1
                    return NestTarget(count_box, cache_key)

    def _make_nest_cache_key(self, count_box, denominator):
        action_name = self.queues[0].__name__ if self.queues else 'unknown'
        screen_height = max(self.height_of_screen(1), 1)
        row_y = (count_box.y + count_box.height / 2) / screen_height
        row_slot = round(row_y / 0.02)
        # 使用粗粒度行槽位，避免 OCR 坐标轻微抖动导致同一目标被重复点击。
        return f'{action_name}:{denominator}:{row_slot}'


def convert_image_to_negative(img):
    to_gray = False
    _mat = img
    if len(_mat.shape) == 3:
        to_gray = True
        _mat = cv2.cvtColor(_mat, cv2.COLOR_BGR2GRAY)
    _, _mat = cv2.threshold(_mat, 80, 255, cv2.THRESH_BINARY)
    _mat = cv2.bitwise_not(_mat)
    if to_gray:
        _mat = cv2.cvtColor(_mat, cv2.COLOR_GRAY2BGR)
    return _mat


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=NightmareNestTask, debug=True)
