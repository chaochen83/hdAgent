import unittest
from unittest.mock import AsyncMock, patch

from backend.langgraph_agent import intent_node
from backend.schemas import ChatMessage, GraphState


class IntentNodeTests(unittest.IsolatedAsyncioTestCase):
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    async def test_sets_product_model_when_current_model_is_missing(
        self, mock_detect, _mock_board_names, _mock_resolve_board
    ):
        mock_detect.return_value = {
            "intent": "general_chat",
            "product_model": None,
            "reply": "",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="MaTouch_ESP32S3的supply voltage是多少？")],
            current_product_model=None,
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "set_product_model")
        self.assertEqual(result.matched_product_model, "MaTouch_ESP32S3")

    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    async def test_keeps_general_chat_when_question_mentions_current_model(
        self, mock_resolve_board, mock_detect, _mock_board_names
    ):
        mock_detect.return_value = {
            "intent": "general_chat",
            "product_model": None,
            "reply": "",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="MaTouch_ESP32S3的supply voltage是多少？")],
            current_product_model="MaTouch_ESP32S3",
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "general_chat")
        self.assertEqual(result.matched_product_model, "MaTouch_ESP32S3")

    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    async def test_switches_product_model_when_user_mentions_different_model(
        self, mock_resolve_board, mock_detect, _mock_board_names
    ):
        mock_detect.return_value = {
            "intent": "general_chat",
            "product_model": None,
            "reply": "",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="ESP32-S3-WROOM-1的supply voltage是多少？")],
            current_product_model="MaTouch_ESP32S3",
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "set_product_model")
        self.assertEqual(result.matched_product_model, "ESP32-S3-WROOM-1")

    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    async def test_respects_llm_set_product_model_decision(
        self, mock_resolve_board, mock_detect, _mock_board_names
    ):
        mock_detect.return_value = {
            "intent": "set_product_model",
            "product_model": "MaTouch_ESP32S3",
            "reply": "明白了，您要问的是MaTouch_ESP32S3。",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="我们切到MaTouch_ESP32S3吧")],
            current_product_model="ESP32-S3-WROOM-1",
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "set_product_model")
        self.assertEqual(result.matched_product_model, "MaTouch_ESP32S3")

    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    async def test_explicit_switch_phrase_forces_set_product_model(
        self, mock_resolve_board, mock_detect, _mock_board_names
    ):
        mock_detect.return_value = {
            "intent": "general_chat",
            "product_model": None,
            "reply": "",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="我们切到MaTouch_ESP32S3吧，后面都按这个回答")],
            current_product_model="MaTouch_ESP32S3",
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "set_product_model")
        self.assertEqual(result.matched_product_model, "MaTouch_ESP32S3")

    @patch("backend.langgraph_agent.list_active_board_names", return_value=[])
    @patch("backend.langgraph_agent.detect_intent_with_llm", new_callable=AsyncMock)
    @patch("backend.langgraph_agent.resolve_board_for_chat", return_value=None)
    async def test_question_with_current_model_name_does_not_switch_context(
        self, mock_resolve_board, mock_detect, _mock_board_names
    ):
        mock_detect.return_value = {
            "intent": "general_chat",
            "product_model": None,
            "reply": "",
        }
        state = GraphState(
            messages=[ChatMessage(role="user", content="基于MaTouch_ESP32S3，I2C引脚是哪两个？")],
            current_product_model="MaTouch_ESP32S3",
            provider="deepseek",
            model=None,
        )

        result = await intent_node(state)

        self.assertEqual(result.intent, "general_chat")
        self.assertEqual(result.matched_product_model, "MaTouch_ESP32S3")


if __name__ == "__main__":
    unittest.main()
