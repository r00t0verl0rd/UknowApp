export function getCurrentProfile(request) { return request("/api/panel/me"); }

export function getAdminBootstrap(request) { return Promise.all([request("/api/admin/users"), request("/api/admin/overview")]); }

export function getTeacherGraph(request) { return request("/api/panel/graph"); }

export function getPanelConversations(request) { return request("/api/panel/conversations"); }

export function getPersonalConversations(request) { return request("/api/panel/personal-conversations"); }

export function getInboxData(request) { return Promise.all([getPanelConversations(request), getPersonalConversations(request)]); }
\nconst API = import.meta.env.VITE_API_BASE_URL || "";\n\nexport function createPanelEventSource() {\n  return new EventSource(API + "/api/panel/events", { withCredentials: true });\n}\n