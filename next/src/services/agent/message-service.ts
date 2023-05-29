import type { Message } from "../../types/agentTypes";
import {
  MESSAGE_TYPE_GOAL,
  MESSAGE_TYPE_SYSTEM,
  MESSAGE_TYPE_THINKING,
} from "../../types/agentTypes";
import { translate } from "../../utils/translations";
import type { Analysis } from "./analysis";
import axios from "axios";

class MessageService {
  private isRunning: boolean;
  private readonly renderMessage: (message: Message) => void;

  constructor(renderMessage: (message: Message) => void) {
    this.isRunning = false;
    this.renderMessage = renderMessage;
  }

  setIsRunning(isRunning: boolean) {
    this.isRunning = isRunning;
  }

  sendMessage(message: Message) {
    if (this.isRunning) {
      this.renderMessage(message);
    }
  }

  sendGoalMessage(goal: string) {
    this.sendMessage({ type: MESSAGE_TYPE_GOAL, value: goal });
  }

  sendLoopMessage() {
    this.sendMessage({
      type: MESSAGE_TYPE_SYSTEM,
      value: translate("DEMO_LOOPS_REACHED", "errors"),
    });
  }

  sendManualShutdownMessage() {
    this.sendMessage({
      type: MESSAGE_TYPE_SYSTEM,
      value: translate("AGENT_MANUALLY_SHUT_DOWN", "errors"),
    });
  }

  sendCompletedMessage() {
    this.sendMessage({
      type: MESSAGE_TYPE_SYSTEM,
      value: translate("ALL_TASKS_COMPLETETD", "errors"),
    });
  }

  sendAnalysisMessage(analysis: Analysis) {
    let message = "⏰ Generating response...";
    if (analysis.action == "search") {
      message = `🔍 Searching the web for "${analysis.arg}"...`;
    }
    if (analysis.action == "wikipedia") {
      message = `🌐 Searching Wikipedia for "${analysis.arg}"...`;
    }
    if (analysis.action == "image") {
      message = `🎨 Generating an image with prompt: "${analysis.arg}"...`;
    }
    if (analysis.action == "code") {
      message = `💻 Writing code...`;
    }

    this.sendMessage({
      type: MESSAGE_TYPE_SYSTEM,
      value: message,
    });
  }

  sendThinkingMessage() {
    this.sendMessage({ type: MESSAGE_TYPE_THINKING, value: "" });
  }

  sendErrorMessage(e: unknown) {
    let message = "ERROR_RETRIEVE_INITIAL_TASKS";

    if (axios.isAxiosError(e)) {
      if (e.response?.status === 429) message = "ERROR_API_KEY_QUOTA";
      if (e.response?.status === 404) message = "ERROR_OPENAI_API_KEY_NO_GPT4";
      else message = "ERROR_ACCESSING_OPENAI_API_KEY";
    } else if (typeof e == "string") {
      message = e;
    }

    this.sendMessage({ type: MESSAGE_TYPE_SYSTEM, value: translate(message, "errors") });
  }
}

export default MessageService;
