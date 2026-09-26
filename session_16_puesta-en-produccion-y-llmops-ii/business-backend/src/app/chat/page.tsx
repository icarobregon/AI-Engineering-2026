import { cookies } from "next/headers";

import { getSession } from "@/lib/estimator/sessions";
import type { SessionInfo } from "@/lib/estimator/contracts";
import { SESSION_COOKIE } from "./session-cookie";
import { ChatView } from "./chat-view";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const sessionId = (await cookies()).get(SESSION_COOKIE)?.value ?? null;

  // Not fatal: the panel is context, not the point of the screen. A session the
  // AI service no longer knows renders as "sin conversación abierta".
  let info: SessionInfo | null = null;
  if (sessionId) {
    try {
      info = await getSession(sessionId);
    } catch {
      info = null;
    }
  }

  return <ChatView info={info} />;
}
