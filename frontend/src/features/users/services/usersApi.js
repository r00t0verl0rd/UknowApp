export function createUser(request, payload) { return request("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }); }

export function updateUser(request, userId, payload) { return request("/api/admin/users/" + userId, { method: "PATCH", body: JSON.stringify(payload) }); }

export function deleteUser(request, userId) { return request("/api/admin/users/" + userId, { method: "DELETE" }); }

export function issuePanelAccessCode(request, userId) { return request("/api/admin/users/" + userId + "/access-code", { method: "POST" }); }

export function createAssignment(request, teacherId, studentId) { return request("/api/admin/assignments", { method: "POST", body: JSON.stringify({ teacher_id: Number(teacherId), student_id: Number(studentId) }) }); }

export function disconnectUserTelegram(request, userId) { return request("/api/admin/users/" + userId + "/disconnect-telegram", { method: "POST" }); }

export function createUserConnectionCode(request, userId) { return request("/api/admin/users/" + userId + "/connection-code", { method: "POST" }); }

export function unassignStudent(request, studentId) { return request("/api/admin/assignments/" + studentId, { method: "DELETE" }); }
