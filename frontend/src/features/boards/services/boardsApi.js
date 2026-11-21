import { request } from "../../../shared/services/api.js";

const BOARD_OBJECTS_URL = "/api/admin/boards/objects";

export function getBoardObjects() {
  return request(BOARD_OBJECTS_URL);
}

export function createBoardObject(payload) {
  return request(BOARD_OBJECTS_URL, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateBoardObjectPosition(objectId, x, y) {
  return request(`${BOARD_OBJECTS_URL}/${objectId}/position`, {
    method: "PATCH",
    body: JSON.stringify({ x, y }),
  });
}

export function deleteBoardObject(objectId) {
  return request(`${BOARD_OBJECTS_URL}/${objectId}`, { method: "DELETE" });
}
