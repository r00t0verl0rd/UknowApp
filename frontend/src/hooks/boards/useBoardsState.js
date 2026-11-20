import { useState } from "react";

export function useBoardsState() {
  const [boardObjects, setBoardObjects] = useState([]);
  return { boardObjects, setBoardObjects };
}
