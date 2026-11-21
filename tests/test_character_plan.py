import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import character_plan as plans


class CharacterPlanTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.reference = self.root/'reference.png'
        self.reference.write_bytes(b'reference fixture')

    def init(self, stances=('normal',), actions=()):
        return plans.initialize(self.root, self.reference, stances, actions)

    def test_two_stances_expand_only_requested_actions(self):
        plan = self.init(('normal', 'combat', 'normal'), ('walk', 'death', 'walk'))
        self.assertEqual([t['id'] for t in plan['tasks']],
                         ['normal-walk', 'combat-walk',
                          'normal-death', 'combat-death'])
        self.assertEqual(plan['facing'], 'right')
        self.assertEqual({t['motion_type'] for t in plan['tasks'] if t['action'] == 'death'}, {'hold_end_pose'})
        self.assertEqual(len({t['job'] for t in plan['tasks']}), 4)
        self.assertEqual(len({t['output'] for t in plan['tasks']}), 4)

    def test_combat_only_idle_does_not_create_normal_stance(self):
        plan = self.init(('combat',), ('idle',))
        self.assertEqual([t['id'] for t in plan['tasks']], ['combat-idle'])
        self.assertEqual(list(plan['stances']), ['combat'])

    def test_second_character_cannot_overwrite_plan(self):
        original = self.init()
        with self.assertRaisesRegex(ValueError, 'already has a character'):
            plans.initialize(self.root, self.reference, ['combat'])
        self.assertEqual(plans.load(self.root), original)

    def test_add_preserves_settings_and_does_not_schedule_idle(self):
        self.init()
        plan = plans.add_action(self.root, ['normal', 'combat'], '動作描述甲', 'return_to_start', 'ground')
        self.assertEqual([t['id'] for t in plan['tasks']],
                         ['normal-custom-001', 'combat-custom-001'])
        plan = plans.add_action(self.root, ['combat'], '動作描述乙', 'return_to_start', 'ground')
        self.assertEqual(sum(t['id'] == 'combat-idle' for t in plan['tasks']), 0)
        self.assertEqual(plan['tasks'][-1]['id'], 'combat-custom-002')
        self.assertEqual(plan['side'], 256)
        self.assertEqual(plan['reference'], str(self.reference.resolve()))

    def test_ground_action_only_requires_prepared_stance(self):
        self.init(('normal', 'combat'), ['walk'])
        with self.assertRaisesRegex(ValueError, 'Record the stance'):
            plans.update_task(self.root, 'normal-walk', 'running')
        plans.record_stance(self.root, 'normal', self.reference, self.reference, self.reference)
        plan = plans.update_task(self.root, 'normal-walk', 'running')
        self.assertEqual(plan['tasks'][0]['status'], 'running')
        with self.assertRaisesRegex(ValueError, 'Record the stance'):
            plans.update_task(self.root, 'combat-walk', 'running')

    def test_invalid_add_does_not_change_saved_plan(self):
        self.init()
        original = plans.load(self.root)
        for stances, description, kind in [(['normal'], '', 'loop'), (['other'], 'walk', 'loop'),
                                           (['combat'], 'attack', 'paused')]:
            with self.assertRaises(ValueError):
                plans.add_action(self.root, stances, description, kind, 'ground')
            self.assertEqual(plans.load(self.root), original)

    def test_missing_artifact_does_not_change_progress(self):
        original = self.init(actions=['idle'])
        with self.assertRaisesRegex(ValueError, 'Missing file'):
            plans.update_task(self.root, 'normal-idle', 'completed',
                              {'source_video': self.root/'missing', 'animation': self.reference})
        self.assertEqual(plans.load(self.root), original)
        self.assertIsInstance(json.loads(plans.plan_path(self.root).read_text()), dict)

    def test_context_is_explicit_and_independent_of_description(self):
        self.init(('combat',))
        for description in ('任意動作內容甲', '任意動作內容乙'):
            plan = plans.add_action(self.root, ['combat'], description, 'return_to_start', 'ground')
            task = plan['tasks'][-1]
            self.assertEqual((task['pipeline'], task['entry_reference'], task['vertical_alignment']),
                             ('standard', 'prepared_stance', 'none'))
            self.assertEqual(task['depends_on'], [])
            self.assertFalse(any(t['action']=='jump' for t in plan['tasks']))
        plan = plans.add_action(self.root, ['combat'], description, 'return_to_start', 'air')
        task = plan['tasks'][-1]
        self.assertEqual((task['pipeline'], task['entry_reference'], task['vertical_alignment']),
                         ('airborne', 'airborne', 'waist'))
        self.assertEqual(task['depends_on'], ['combat-jump'])

    def test_jump_option_expands_to_one_bundle_per_stance(self):
        plan = self.init(('normal', 'combat'), ['jump'])
        tasks = [t for t in plan['tasks'] if t['pipeline']=='jump']
        self.assertEqual([t['id'] for t in tasks], ['normal-jump', 'combat-jump'])
        self.assertTrue(all(t['entry_reference']=='prepared_stance' and t['vertical_alignment']=='waist' for t in tasks))

    def test_explicit_base_bundle_does_not_add_an_airborne_custom_action(self):
        self.init(('combat',))
        plan=plans.add_action(self.root,['combat'],'base phases','hold_end_pose','air',pipeline='jump')
        self.assertEqual([t['id'] for t in plan['tasks']],['combat-jump'])
        self.assertEqual(plan['tasks'][-1]['entry_reference'],'prepared_stance')
        self.assertEqual(plan['tasks'][-1]['description'],'base phases')
        again=plans.add_action(self.root,['combat'],'base phases','hold_end_pose','air',pipeline='jump')
        self.assertEqual(len(again['tasks']),1)

    def test_explicit_pipeline_cannot_override_selected_environment(self):
        self.init()
        for pipeline in ('airborne','jump'):
            with self.assertRaises(ValueError):
                plans.add_action(self.root,['normal'],'motion','hold_end_pose','ground',pipeline=pipeline)

    def test_air_requires_completed_jump_and_recorded_reference(self):
        self.init()
        plan = plans.add_action(self.root, ['normal'], '任意動作內容', 'return_to_start', 'air')
        current = plan['tasks'][-1]['id']
        with self.assertRaisesRegex(ValueError, 'dependency'):
            plans.update_task(self.root, current, 'running')
        plans.record_stance(self.root, 'normal', self.reference, self.reference, self.reference)
        plans.update_task(self.root, 'normal-jump', 'completed',
                          {key:self.reference for key in ('source_video','rise_animation','fall_animation','airborne_profile')})
        with self.assertRaisesRegex(ValueError, 'airborne reference'):
            plans.update_task(self.root, current, 'running')
        plans.record_airborne(self.root, 'normal', self.reference)
        plan = plans.update_task(self.root, current, 'running')
        self.assertEqual(plan['tasks'][-1]['status'], 'running')

    def test_missing_environment_does_not_modify_plan(self):
        before = self.init()
        with self.assertRaisesRegex(ValueError, 'environment'):
            plans.add_action(self.root, ['combat'], '任意動作內容', 'return_to_start', None)
        self.assertEqual(plans.load(self.root), before)


if __name__ == '__main__':
    unittest.main()
