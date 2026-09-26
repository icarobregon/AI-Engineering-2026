/**
 * Lives outside actions.ts because a "use server" module may only export async
 * functions — a plain constant there is a build error.
 */
export const SESSION_COOKIE = "chat_session_id";
