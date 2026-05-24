import unittest

from backend.app.services.chat_service import _should_confirm_product_model_switch


class ChatServiceHelpersTests(unittest.TestCase):
    def test_requires_confirmation_when_switching_from_existing_session_model(self):
        self.assertTrue(
            _should_confirm_product_model_switch(
                current_product_model="MaTouch_ESP32S3",
                matched_product_model="ESP32-S3-WROOM-1",
                intent="set_product_model",
                switch_decision=None,
            )
        )

    def test_skips_confirmation_when_no_current_session_model(self):
        self.assertFalse(
            _should_confirm_product_model_switch(
                current_product_model=None,
                matched_product_model="ESP32-S3-WROOM-1",
                intent="set_product_model",
                switch_decision=None,
            )
        )

    def test_skips_confirmation_after_user_has_already_decided(self):
        self.assertFalse(
            _should_confirm_product_model_switch(
                current_product_model="MaTouch_ESP32S3",
                matched_product_model="ESP32-S3-WROOM-1",
                intent="set_product_model",
                switch_decision="no",
            )
        )


if __name__ == "__main__":
    unittest.main()
