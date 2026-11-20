import { useCallback, useEffect, useState } from "react";
import {
  createBoardObject as createBoardObjectRequest,
  deleteBoardObject as deleteBoardObjectRequest,
  getBoardObjects,
  updateBoardObjectPosition,
} from "../../features/boards/services/boardsApi.js";

function removeObjectTree(objects, objectId) {
  const childrenByParent = new Map();
  for (const item of objects) {
    if (!childrenByParent.has(item.parent_id)) childrenByParent.set(item.parent_id, []);
    childrenByParent.get(item.parent_id).push(item.id);
  }

  const removed = new Set();
  const pending = [objectId];
  while (pending.length) {
    const id = pending.pop();
    if (removed.has(id)) continue;
    removed.add(id);
    pending.push(...(childrenByParent.get(id) || []));
  }
  return objects.filter(item => !removed.has(item.id));
}

export function useBoardsState() {
  const [boardObjects, setBoardObjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const objects = await getBoardObjects();
      setBoardObjects(objects);
      return objects;
    } catch (cause) {
      setError(cause.message || "Не удалось загрузить доски");
      throw cause;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    getBoardObjects()
      .then(objects => { if (active) setBoardObjects(objects); })
      .catch(cause => { if (active) setError(cause.message || "Не удалось загрузить доски"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const createObject = useCallback(async payload => {
    setError("");
    try {
      const created = await createBoardObjectRequest(payload);
      setBoardObjects(current => [...current, created]);
      return created;
    } catch (cause) {
      setError(cause.message || "Не удалось создать объект");
      throw cause;
    }
  }, []);

  const moveObject = useCallback(async (objectId, x, y) => {
    setError("");
    try {
      await updateBoardObjectPosition(objectId, x, y);
    } catch (cause) {
      setError(cause.message || "Не удалось переместить объект");
      throw cause;
    }
  }, []);

  const deleteObject = useCallback(async objectId => {
    setError("");
    try {
      await deleteBoardObjectRequest(objectId);
      setBoardObjects(current => removeObjectTree(current, objectId));
    } catch (cause) {
      setError(cause.message || "Не удалось удалить объект");
      throw cause;
    }
  }, []);

  const clearError = useCallback(() => setError(""), []);

  return { boardObjects, loading, error, clearError, createObject, deleteObject, moveObject, reload };
}
