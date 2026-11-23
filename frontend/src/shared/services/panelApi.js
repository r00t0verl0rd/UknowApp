export function getCurrentProfile(request) { return request("/api/panel/me"); }

export function getAdminBootstrap(request) { return Promise.all([request("/api/admin/users"), request("/api/admin/overview")]); }

export function getInboxData(request) {
  return Promise.all([
    request("/api/panel/conversations"),
    request("/api/panel/personal-conversations"),
  ]);
}
