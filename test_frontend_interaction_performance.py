import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class FrontendInteractionPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ux = (ROOT / "ux.js").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.personal_notifications = (ROOT / "personal_notifications.js").read_text(encoding="utf-8")

    def test_draft_capture_is_deferred_out_of_input_handler(self):
        self.assertIn("overlay.addEventListener('input',scheduleCapture)", self.ux)
        self.assertIn("requestIdleCallback", self.ux)
        self.assertNotIn("overlay.addEventListener('input',capture)", self.ux)

    def test_conflict_preview_does_not_fetch_remote_weeks(self):
        marker = "function attachConflictPreview"
        section = self.ux[self.ux.index(marker):]
        section = section[:section.index("// The single-event action")]
        self.assertIn("cachedWeekSchedule(key)", section)
        self.assertNotIn("fetchWeekSchedule(", section)

    def test_payment_toggle_is_single_click_and_optimistic(self):
        group = self.app[self.app.index("async function setGroupMemberPaidState"):]
        group = group[:group.index("function closeActionMenu")]
        self.assertNotIn("confirm(", group)
        self.assertLess(group.index("applyReturnedLesson("), group.index("apiFetch('/mark_paid'"))

        direct = self.app[self.app.index("bindReliableTap(document.getElementById('btn-action-paid')"):]
        direct = direct[:direct.index("document.getElementById('btn-action-subscription').onclick")]
        self.assertNotIn("confirm(", direct)
        self.assertNotIn("paid-confirm-overlay", direct)
        self.assertLess(direct.index("applyReturnedLesson("), direct.index("apiFetch('/mark_paid'"))

        reliable = self.app[self.app.index("function bindReliableTap"):]
        reliable = reliable[:reliable.index("function startMove")]
        self.assertIn("button.addEventListener('pointerdown'", reliable)
        self.assertLess(reliable.index("run(event)"), reliable.index("button.addEventListener('pointerup'"))
        self.assertIn("button.dataset.actionBusy", reliable)

        finance = self.app[self.app.index("async function changeStudentLessonPayment"):]
        finance = finance[:finance.index("let inviteView")]
        self.assertNotIn("confirm(", finance)
        self.assertNotIn("direct: 'Отметить занятие оплаченным'", finance)
        self.assertNotIn("reverse: 'Снять оплату'", finance)

    def test_actions_do_not_use_browser_confirmation_prompts(self):
        self.assertNotIn("confirm(", self.app)
        self.assertNotIn("confirm(", self.personal_notifications)
        self.assertNotIn("Для подтверждения введите имя ученика", self.app)
        self.assertNotIn("paid-confirm-overlay", self.app)
        self.assertNotIn("day-off-warning-overlay", self.app)

    def test_self_hosted_frontend_uses_its_own_api_origin(self):
        prelude = self.app[:self.app.index("const START_HOUR")]
        self.assertIn("? window.location.origin", prelude)
        self.assertIn("const SUPPORTS_BOOTSTRAP = selfHostedBot3 || requestedBot3", prelude)
        self.assertNotIn("window.location.origin === TEST_API_ORIGIN", prelude)


if __name__ == "__main__":
    unittest.main()
